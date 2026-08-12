"""Orchestration de l'import Maxi dans les tables natives de Souschef."""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..adapters.maxi_capture import MaxiCaptureAdapter
from ..models import Product, Store
from .normalize import land_offers, normalize_offers


class UnknownMaxiStoreError(ValueError):
    pass


def import_maxi_catalogue(
    session: Session, adapter: MaxiCaptureAdapter
) -> dict[str, int]:
    """Upserte les produits, puis fait passer leurs prix par staging.

    La transaction appartient à l'appelant. Aucun magasin n'est créé ici :
    l'identité et l'adresse du magasin doivent déjà être curées dans Souschef.
    """
    store = session.query(Store).filter_by(
        external_key=adapter.store_external_key
    ).one_or_none()
    if store is None:
        raise UnknownMaxiStoreError(
            f"Magasin Souschef inconnu: {adapter.store_external_key!r}"
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
