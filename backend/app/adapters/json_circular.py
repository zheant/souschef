"""Adaptateur JSON du CircularPort — v1.

Lit ``<seed_dir>/raw_offers.json`` : une liste d'objets RawOfferDTO. Le vrai
scraper remplacera cette classe, à signature identique (voir README).
"""

from __future__ import annotations

import json
from pathlib import Path

from ..ports.dto import RawOfferDTO


class JsonCircularAdapter:
    def __init__(self, seed_dir: str | Path):
        self._path = Path(seed_dir) / "raw_offers.json"

    def fetch_week(self, store_id: str, week: str) -> list[RawOfferDTO]:
        offers = [
            RawOfferDTO(**o)
            for o in json.loads(self._path.read_text(encoding="utf-8"))
        ]
        return [
            o
            for o in offers
            if o.store_external_key == store_id and o.week == week
        ]

    def all_weeks(self) -> list[str]:
        """Utilitaire de seeding : toutes les semaines présentes dans la source."""
        offers = json.loads(self._path.read_text(encoding="utf-8"))
        return sorted({o["week"] for o in offers})

    def all_store_keys(self) -> list[str]:
        offers = json.loads(self._path.read_text(encoding="utf-8"))
        return sorted({o["store_external_key"] for o in offers})
