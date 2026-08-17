"""Compatibilité de l'import Maxi dans les tables natives de Souschef."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..adapters.maxi_capture import MaxiCaptureAdapter
from .retailer_catalogue import (
    UnknownRetailerStoreError,
    import_retailer_catalogue,
)


class UnknownMaxiStoreError(UnknownRetailerStoreError):
    pass


def import_maxi_catalogue(
    session: Session, adapter: MaxiCaptureAdapter
) -> dict[str, int]:
    """Upserte les produits, puis fait passer leurs prix par staging.

    La transaction appartient à l'appelant. Aucun magasin n'est créé ici :
    l'identité et l'adresse du magasin doivent déjà être curées dans Souschef.
    """
    try:
        return import_retailer_catalogue(session, adapter)
    except UnknownRetailerStoreError as error:
        raise UnknownMaxiStoreError(str(error)) from error
