"""Port d'acquisition des circulaires.

v1 : adaptateur JSON (app.adapters.json_circular). Plus tard : vrai scraper.
Le port est exécuté EN LOT par la couche d'ingestion, jamais dans le chemin
d'une requête HTTP.
"""

from typing import Protocol

from .dto import RawOfferDTO


class CircularPort(Protocol):
    def fetch_week(self, store_id: str, week: str) -> list[RawOfferDTO]:
        """Retourne les offres brutes d'un magasin pour une semaine ISO (YYYY-Www)."""
        ...
