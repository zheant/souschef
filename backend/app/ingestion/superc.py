"""Orchestration de l'import Super C dans les tables natives de Souschef."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..adapters.superc_capture import SuperCCaptureAdapter
from .retailer_catalogue import (
    UnknownRetailerStoreError,
    import_retailer_catalogue,
)


class UnknownSuperCStoreError(UnknownRetailerStoreError):
    pass


def import_superc_catalogue(
    session: Session, adapter: SuperCCaptureAdapter
) -> dict[str, int]:
    try:
        return import_retailer_catalogue(session, adapter)
    except UnknownRetailerStoreError as error:
        raise UnknownSuperCStoreError(str(error)) from error
