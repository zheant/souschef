"""``OfferResolutionModule`` — résolution semi-manuelle des offres non
mappées (D15/D18, docs/deviations.md).

Même convention que ``planning.py``/``household.py``/``catalog.py`` :
``session: Session`` explicite en premier paramètre (voir la docstring de
``planning.py`` pour la raison), DTO dataclasses, exceptions typées.

**N'écrit jamais dans ``staging.raw_offer``** — c'est l'invariant central de
ce module. Confirmer une correspondance (attacher ou créer un produit) ne
fait que corriger ``market.product_mapping`` ; c'est le prochain passage en
lot de ``ingestion/normalize.py::normalize_offers`` qui reconsultera cette
table et résoudra les offres, historiques et futures. Une route HTTP qui
mettrait à jour ``mapping_status`` directement contournerait l'ingestion en
lot — exactement le raccourci que ``CLAUDE.md`` interdit (« Chemin port →
staging → normalisation, jamais de raccourci »). C'est le deuxième bug de
D15 : l'ancienne route ``POST /api/ingredients/map`` faisait précisément ça,
sans jamais créer de prix pour les offres concernées.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import (
    CanonicalIngredient, MappingStatus, Product, ProductMapping, RawOffer, Store,
)


class UnknownStoreError(LookupError):
    """Aucun magasin avec cet ``external_key`` (l'API traduit en 404)."""


class UnknownProductError(LookupError):
    """Aucun produit avec cet id (l'API traduit en 404)."""


class UnknownCanonicalIngredientError(ValueError):
    """Ingrédient canonique inconnu pour un nouveau produit (l'API traduit
    en 422)."""


@dataclass(frozen=True)
class UnresolvedOffer:
    store_external_key: str
    raw_text: str
    occurrences: int


@dataclass(frozen=True)
class NewProductSpec:
    canonical_ingredient_id: str
    brand: str
    package_qty_in_base_unit: Decimal
    package_unit: str
    tax_rate: Decimal


@dataclass(frozen=True)
class ResolutionResult:
    store_external_key: str
    raw_text: str
    product_id: int
    created_new_product: bool
    #: Offres en ``staging.raw_offer`` (statut ``unmapped``) pour ce
    #: (magasin, texte brut) qui seront résolues au prochain passage de
    #: ``normalize_offers`` — pas encore résolues par cet appel.
    pending_offers: int


def list_unresolved(session: Session) -> tuple[UnresolvedOffer, ...]:
    """File d'attente de résolution : offres en staging sans correspondance,
    groupées par (magasin, texte brut)."""
    rows = session.execute(
        select(
            RawOffer.store_external_key,
            RawOffer.payload["raw_text"].astext.label("raw_text"),
            func.count().label("occurrences"),
        )
        .where(RawOffer.mapping_status == MappingStatus.unmapped)
        .group_by(RawOffer.store_external_key, RawOffer.payload["raw_text"].astext)
        .order_by(func.count().desc())
    ).all()
    return tuple(
        UnresolvedOffer(
            store_external_key=r.store_external_key, raw_text=r.raw_text,
            occurrences=r.occurrences,
        )
        for r in rows
    )


def attach_existing_product(
    session: Session,
    store_external_key: str,
    raw_text: str,
    product_id: int,
    confirmed_by: str,
) -> ResolutionResult:
    store = _load_store(session, store_external_key)
    if session.get(Product, product_id) is None:
        raise UnknownProductError(f"Produit {product_id} introuvable.")
    _upsert_confirmed_mapping(session, store.id, raw_text, product_id, confirmed_by)
    return ResolutionResult(
        store_external_key=store_external_key, raw_text=raw_text,
        product_id=product_id, created_new_product=False,
        pending_offers=_count_pending(session, store_external_key, raw_text),
    )


def create_and_attach_product(
    session: Session,
    store_external_key: str,
    raw_text: str,
    spec: NewProductSpec,
    confirmed_by: str,
) -> ResolutionResult:
    store = _load_store(session, store_external_key)
    if session.get(CanonicalIngredient, spec.canonical_ingredient_id) is None:
        raise UnknownCanonicalIngredientError(
            f"Ingrédient inconnu : '{spec.canonical_ingredient_id}'."
        )
    product = Product(
        canonical_ingredient_id=spec.canonical_ingredient_id,
        brand=spec.brand,
        package_qty_in_base_unit=spec.package_qty_in_base_unit,
        package_unit=spec.package_unit,
        tax_rate=spec.tax_rate,
        # Placeholder unique le temps d'obtenir l'id de substitution — pas
        # d'external_key de source pour un produit créé manuellement.
        external_key="",
    )
    session.add(product)
    session.flush()
    # Convention d'ingestion (traçabilité/affichage), pas une contrainte
    # imposée par le solveur : celui-ci nomme ses variables depuis l'id de
    # substitution, jamais depuis external_key (D18, docs/deviations.md).
    product.external_key = f"manual-{product.id}"
    session.flush()

    _upsert_confirmed_mapping(
        session, store.id, raw_text, product.id, confirmed_by
    )
    return ResolutionResult(
        store_external_key=store_external_key, raw_text=raw_text,
        product_id=product.id, created_new_product=True,
        pending_offers=_count_pending(session, store_external_key, raw_text),
    )


def _load_store(session: Session, store_external_key: str) -> Store:
    store = session.scalar(
        select(Store).where(Store.external_key == store_external_key)
    )
    if store is None:
        raise UnknownStoreError(f"Magasin '{store_external_key}' introuvable.")
    return store


def _upsert_confirmed_mapping(
    session: Session,
    store_id: int,
    raw_text: str,
    product_id: int,
    confirmed_by: str,
) -> None:
    # on_conflict_do_UPDATE, pas do_nothing : contrairement à l'upsert
    # automatique de normalize_offers (qui ne doit jamais écraser une
    # confirmation), une confirmation humaine doit pouvoir en corriger une
    # autre — c'est le seul chemin de correction possible.
    stmt = (
        pg_insert(ProductMapping)
        .values(
            store_id=store_id, raw_text=raw_text, product_id=product_id,
            confidence=Decimal("1.000"), confirmed_by=confirmed_by,
        )
        .on_conflict_do_update(
            index_elements=["store_id", "raw_text"],
            set_={
                "product_id": product_id, "confidence": Decimal("1.000"),
                "confirmed_by": confirmed_by,
            },
        )
    )
    session.execute(stmt)


def _count_pending(session: Session, store_external_key: str, raw_text: str) -> int:
    return session.scalar(
        select(func.count())
        .select_from(RawOffer)
        .where(
            RawOffer.store_external_key == store_external_key,
            RawOffer.mapping_status == MappingStatus.unmapped,
            RawOffer.payload["raw_text"].astext == raw_text,
        )
    )
