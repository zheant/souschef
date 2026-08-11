"""Tests directs de ``services/offer_resolution.py`` (OfferResolutionModule),
contre PostgreSQL réel — preuve directe du correctif D15/D18
(docs/deviations.md) : une confirmation manuelle est désormais reconsultée
par ``normalize_offers``, et la clé de mapping est (magasin, texte brut),
pas texte brut seul.
"""

from __future__ import annotations

from decimal import Decimal
from datetime import date

import pytest
from sqlalchemy import func, select

from app.ingestion.normalize import land_offers, normalize_offers
from app.models import Price, Product, ProductMapping, Store
from app.ports.dto import RawOfferDTO
from app.services import offer_resolution
from tests.db_fixtures import db_session, test_engine, toy_seeded  # noqa: F401


class _FakePort:
    """Port de circulaire factice : offres injectées à la main, aucune
    résolution automatique via product_external_key (None partout) — c'est
    exactement le cas que product_mapping doit couvrir."""

    def __init__(self, by_store_week: dict[tuple[str, str], list[RawOfferDTO]]):
        self._offers = by_store_week

    def fetch_week(self, store_id, week):
        return self._offers.get((store_id, week), [])


def _offer(store: str, week: str, raw_text: str, valid_from: str, valid_to: str):
    return RawOfferDTO(
        store_external_key=store, week=week, raw_text=raw_text,
        product_external_key=None, price_cents_cad=299,
        regular_price_cents_cad=299, is_promo=False,
        valid_from=valid_from, valid_to=valid_to,
    )


def _product_id(session, external_key: str) -> int:
    return session.scalar(select(Product.id).where(Product.external_key == external_key))


def test_confirmation_resolves_historical_and_future_offers(db_session):
    """Le scénario exact documenté comme cassé dans D15 : une offre confirmée
    reste sans prix tant que normalize_offers ne la reconsulte pas — et une
    nouvelle offre la semaine suivante, même raw_text, doit aussi en profiter."""
    raw_text = "Riz Mystère 5kg"
    port = _FakePort({
        ("toy_store", "2026-W40"): [
            _offer("toy_store", "2026-W40", raw_text, "2026-08-31", "2026-09-06")
        ],
    })
    land_offers(db_session, port, "toy_store", "2026-W40")
    normalize_offers(db_session)

    unresolved = offer_resolution.list_unresolved(db_session)
    assert any(
        u.store_external_key == "toy_store" and u.raw_text == raw_text
        for u in unresolved
    )

    riz_id = _product_id(db_session, "riz_400g")
    result = offer_resolution.attach_existing_product(
        db_session, "toy_store", raw_text, riz_id, "tester",
    )
    assert result.product_id == riz_id
    assert result.created_new_product is False
    # L'offre de W40 est encore unmapped : la confirmation elle-même ne l'a
    # pas touchée (invariant du module — jamais staging.raw_offer).
    assert result.pending_offers == 1

    def _has_price(valid_from: date) -> bool:
        return bool(db_session.scalar(
            select(func.count()).select_from(Price).where(
                Price.product_id == riz_id, Price.valid_from == valid_from
            )
        ))

    assert not _has_price(date(2026, 8, 31))

    # Semaine suivante, même (magasin, raw_text) : land + un seul passage de
    # normalize_offers doit résoudre À LA FOIS l'offre historique (W40,
    # restée unmapped) et la nouvelle (W41).
    port2 = _FakePort({
        ("toy_store", "2026-W41"): [
            _offer("toy_store", "2026-W41", raw_text, "2026-09-07", "2026-09-13")
        ],
    })
    land_offers(db_session, port2, "toy_store", "2026-W41")
    normalize_offers(db_session)

    assert _has_price(date(2026, 8, 31))
    assert _has_price(date(2026, 9, 7))


def test_same_raw_text_different_stores_resolve_independently(db_session):
    """La clé de mapping est (store_id, raw_text), pas raw_text seul (D18) :
    un même libellé chez deux magasins ne doit jamais être confondu."""
    second = Store(
        external_key="second_store", banner="Deuxième bannière",
        address="1 rue Test", lat=Decimal("45.5"), lng=Decimal("-73.6"),
    )
    db_session.add(second)
    db_session.flush()

    raw_text = "Poulet, format familial"
    riz_id = _product_id(db_session, "riz_400g")
    lentille_id = _product_id(db_session, "lentille_500g")

    offer_resolution.attach_existing_product(
        db_session, "toy_store", raw_text, riz_id, "tester",
    )
    offer_resolution.attach_existing_product(
        db_session, "second_store", raw_text, lentille_id, "tester",
    )

    toy_store_id = db_session.scalar(
        select(Store.id).where(Store.external_key == "toy_store")
    )
    mappings = {
        (m.store_id, m.raw_text): m.product_id
        for m in db_session.scalars(
            select(ProductMapping).where(ProductMapping.raw_text == raw_text)
        )
    }
    assert mappings[(toy_store_id, raw_text)] == riz_id
    assert mappings[(second.id, raw_text)] == lentille_id


def test_create_and_attach_product_gets_synthetic_external_key(db_session):
    spec = offer_resolution.NewProductSpec(
        canonical_ingredient_id="riz", brand="Marque Test",
        package_qty_in_base_unit=Decimal("750"), package_unit="750 g",
        tax_rate=Decimal("0"),
    )
    result = offer_resolution.create_and_attach_product(
        db_session, "toy_store", "Riz local 750g", spec, "tester",
    )
    assert result.created_new_product is True
    product = db_session.get(Product, result.product_id)
    assert product.external_key == f"manual-{product.id}"
    assert product.canonical_ingredient_id == "riz"
    assert product.package_qty_in_base_unit == Decimal("750")

    with pytest.raises(offer_resolution.UnknownCanonicalIngredientError):
        offer_resolution.create_and_attach_product(
            db_session, "toy_store", "x",
            offer_resolution.NewProductSpec(
                canonical_ingredient_id="inexistant", brand="X",
                package_qty_in_base_unit=Decimal("1"), package_unit="1 u",
                tax_rate=Decimal("0"),
            ),
            "tester",
        )

    with pytest.raises(offer_resolution.UnknownStoreError):
        offer_resolution.attach_existing_product(
            db_session, "magasin_inconnu", "x", result.product_id, "tester",
        )

    with pytest.raises(offer_resolution.UnknownProductError):
        offer_resolution.attach_existing_product(
            db_session, "toy_store", "x", 999_999, "tester",
        )


def test_confirmed_mapping_survives_relanding_but_is_correctable(db_session):
    raw_text = "Format mystère"
    riz_id = _product_id(db_session, "riz_400g")
    lentille_id = _product_id(db_session, "lentille_500g")

    offer_resolution.attach_existing_product(
        db_session, "toy_store", raw_text, riz_id, "tester",
    )

    # L'atterrissage automatique ne doit jamais écraser une confirmation.
    port = _FakePort({
        ("toy_store", "2026-W44"): [
            _offer("toy_store", "2026-W44", raw_text, "2026-09-28", "2026-10-04")
        ],
    })
    land_offers(db_session, port, "toy_store", "2026-W44")
    normalize_offers(db_session)

    mapping = db_session.scalar(
        select(ProductMapping).where(ProductMapping.raw_text == raw_text)
    )
    assert mapping.product_id == riz_id

    # Une deuxième confirmation humaine, elle, peut corriger.
    offer_resolution.attach_existing_product(
        db_session, "toy_store", raw_text, lentille_id, "tester2",
    )
    db_session.expire(mapping)
    mapping = db_session.scalar(
        select(ProductMapping).where(ProductMapping.raw_text == raw_text)
    )
    assert mapping.product_id == lentille_id
    assert mapping.confirmed_by == "tester2"
