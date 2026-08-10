"""Port du catalogue de recettes.

v1 : adaptateur JSON (app.adapters.json_recipe_source). Plus tard : vrai
catalogue (~1000 recettes) — sans toucher au solveur, à l'API ni au front-end.
"""

from typing import Protocol

from .dto import RecipeDTO


class RecipeSourcePort(Protocol):
    def load_all(self) -> list[RecipeDTO]:
        ...
