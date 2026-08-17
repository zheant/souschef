"""Adaptateur JSON du RecipeSourcePort — recettes de seed et importées."""

from __future__ import annotations

import json
from pathlib import Path

from ..ports.dto import RecipeDTO


class JsonRecipeSourceAdapter:
    def __init__(self, seed_dir: str | Path):
        self._path = Path(seed_dir) / "recipes.json"

    def load_all(self) -> list[RecipeDTO]:
        return [RecipeDTO(**r) for r in json.loads(self._path.read_text())]
