"""Ingestion : staging → normalisation.

Deux passes, toutes deux rejouables et idempotentes :

1. ``land_offers`` — les offres brutes du :class:`CircularPort` atterrissent
   telles quelles dans ``staging.raw_offer`` (empreinte sha256 pour dédupliquer
   au rejeu). Rien n'est perdu, rien n'est interprété.
2. ``normalize_offers`` — les offres en staging sont résolues :
   ``product_mapping`` ((magasin, texte brut) → produit précis, D18) est
   consulté et alimenté, le statut passe à ``auto`` quand le produit est
   connu, et une ligne ``market.price`` est upsertée par (produit, magasin,
   valid_from).

C'est ce cheminement — et lui seul — que le vrai scraper empruntera.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import MappingStatus, Price, Product, ProductMapping, RawOffer, Store
from ..ports.circular import CircularPort


def _fingerprint(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def land_offers(
    session: Session, port: CircularPort, store_id: str, week: str
) -> int:
    """Passe 1 : atterrissage brut en ``staging.raw_offer``. Retourne le nombre
    de lignes nouvellement insérées (les doublons de rejeu sont ignorés)."""
    inserted = 0
    for offer in port.fetch_week(store_id, week):
        payload = offer.model_dump(mode="json")
        stmt = (
            pg_insert(RawOffer)
            .values(
                store_external_key=offer.store_external_key,
                week=offer.week,
                payload=payload,
                payload_fingerprint=_fingerprint(payload),
                mapping_status=MappingStatus.unmapped,
            )
            .on_conflict_do_nothing(
                index_elements=["store_external_key", "week", "payload_fingerprint"]
            )
        )
        inserted += session.execute(stmt).rowcount or 0
    return inserted


def normalize_offers(session: Session) -> dict[str, int]:
    """Passe 2 : résolution des offres en staging vers ``market``.

    Idempotente : re-exécuter ne duplique ni mapping ni prix.

    Ordre de résolution par offre, le premier qui répond gagne (D15/D18,
    docs/deviations.md) :
    1. ``product_external_key`` connu (chemin JSON-seed) ;
    2. ``product_mapping`` confirmé pour ``(store_id, raw_text)`` — c'est le
       chemin qui manquait avant D18 : une confirmation manuelle via
       ``services/offer_resolution.py`` n'était jamais reconsultée ici ;
    3. sinon ``unmapped``.
    """
    stats = {"auto": 0, "unmapped": 0, "prices_upserted": 0}
    # Résolution external_key → entité : c'est ici (et dans product_mapping),
    # pas dans les clés primaires, que l'instabilité du monde extérieur est
    # absorbée.
    known_products = {
        p.external_key: p for p in session.scalars(select(Product)).all()
    }
    products_by_id = {p.id: p for p in known_products.values()}
    store_ids_by_key = {
        s.external_key: s.id for s in session.scalars(select(Store)).all()
    }
    mappings_by_store_and_raw_text = {
        (m.store_id, m.raw_text): m
        for m in session.scalars(
            select(ProductMapping).where(ProductMapping.product_id.is_not(None))
        ).all()
    }

    offers = session.scalars(
        select(RawOffer).where(
            RawOffer.mapping_status.in_(
                [MappingStatus.unmapped, MappingStatus.auto]
            )
        )
    ).all()

    for raw in offers:
        p = raw.payload
        store_id = store_ids_by_key.get(p["store_external_key"])
        product = known_products.get(p.get("product_external_key") or "")
        if product is None and store_id is not None:
            mapping = mappings_by_store_and_raw_text.get((store_id, p["raw_text"]))
            if mapping is not None:
                product = products_by_id.get(mapping.product_id)

        if store_id is not None:
            # Alimente la table de mapping (store, texte brut) → produit —
            # ne l'écrase jamais si une confirmation existe déjà
            # (``on_conflict_do_nothing`` : seule ``offer_resolution.py``
            # peut corriger une confirmation, jamais l'atterrissage
            # automatique). Sans magasin résolu, pas de ligne : la clé
            # ``store_id`` est NOT NULL — un magasin inconnu est une autre
            # classe de problème.
            mapping_stmt = (
                pg_insert(ProductMapping)
                .values(
                    store_id=store_id,
                    raw_text=p["raw_text"],
                    product_id=product.id if product else None,
                    confidence=Decimal("1.000") if product else Decimal("0.000"),
                    confirmed_by=None,
                )
                .on_conflict_do_nothing(index_elements=["store_id", "raw_text"])
            )
            session.execute(mapping_stmt)

        if product is None or store_id is None:
            raw.mapping_status = MappingStatus.unmapped
            stats["unmapped"] += 1
            continue

        price_stmt = (
            pg_insert(Price)
            .values(
                product_id=product.id,
                store_id=store_id,
                price_cents_cad=p["price_cents_cad"],
                valid_from=date.fromisoformat(p["valid_from"]),
                valid_to=date.fromisoformat(p["valid_to"]),
                is_promo=p.get("is_promo", False),
                regular_price_cents_cad=p.get("regular_price_cents_cad"),
            )
            .on_conflict_do_update(
                index_elements=["product_id", "store_id", "valid_from"],
                set_={
                    "price_cents_cad": p["price_cents_cad"],
                    "valid_to": date.fromisoformat(p["valid_to"]),
                    "is_promo": p.get("is_promo", False),
                    "regular_price_cents_cad": p.get("regular_price_cents_cad"),
                },
            )
        )
        session.execute(price_stmt)
        raw.mapping_status = MappingStatus.auto
        stats["auto"] += 1
        stats["prices_upserted"] += 1

    return stats
