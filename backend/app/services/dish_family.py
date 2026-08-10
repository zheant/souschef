"""Convention de nommage du seed v1 pour regrouper les variantes d'échelle.

``<id>`` et ``<id>_familial`` partagent le même plat : deux segments d'une
même courbe de coût non linéaire (D16, docs/deviations.md), pas deux plats
distincts. Utilisé au seeding (insertion) et au backfill de migration pour
peupler ``catalog.recipe.dish_family_id`` — c'est une convention du seed
JSON v1, PAS une sémantique générale : un futur catalogue de recettes réel
(1000 recettes, scraper) devra fournir sa propre famille de plat plutôt que
s'appuyer sur un suffixe de nom.
"""

from __future__ import annotations

_FAMILIAL_SUFFIX = "_familial"


def dish_family_id_of(recipe_id: str) -> str:
    """Dérive la famille de plat depuis l'id : ``chili_familial`` et
    ``chili`` retournent tous deux ``chili`` ; un id sans suffixe est sa
    propre famille (singleton)."""
    if recipe_id.endswith(_FAMILIAL_SUFFIX):
        return recipe_id[: -len(_FAMILIAL_SUFFIX)]
    return recipe_id
