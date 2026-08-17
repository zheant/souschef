"""Orchestration commune des catalogues capturés par bannière."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import Product, Store
from ..ports.dto import RawOfferDTO
from .normalize import land_offers, normalize_offers


class CapturedCatalogue(Protocol):
    store_external_key: str
    week: str
    source_name: str

    def product_rows(self) -> list[dict]: ...

    def fetch_week(self, store_id: str, week: str) -> list[RawOfferDTO]: ...


class UnknownRetailerStoreError(ValueError):
    pass


def import_retailer_catalogue(
    session: Session, adapter: CapturedCatalogue
) -> dict[str, int]:
    """Upserte les produits, puis fait passer leurs prix par staging."""
    store = session.query(Store).filter_by(
        external_key=adapter.store_external_key
    ).one_or_none()
    if store is None:
        raise UnknownRetailerStoreError(
            f"Magasin Souschef inconnu pour {adapter.source_name}: "
            f"{adapter.store_external_key!r}"
        )

    product_rows = adapter.product_rows()
    for row in product_rows:
        statement = pg_insert(Product).values(**row).on_conflict_do_update(
            index_elements=["external_key"],
            set_={key: value for key, value in row.items() if key != "external_key"},
        )
        session.execute(statement)
    session.flush()

    landed = land_offers(
        session, adapter, adapter.store_external_key, adapter.week
    )
    normalized = normalize_offers(session)
    return {
        "products_upserted": len(product_rows),
        "offers_landed": landed,
        **normalized,
    }
