"""Entrées du calcul nutritionnel, lues hors base : seed + archive fédérale.

Deux scripts en ont besoin — l'audit de couverture et la proposition
d'appariement. Les laisser charger chacun de leur côté, c'est accepter qu'ils
finissent par travailler sur deux corpus différents et se contredire dans le
même rapport. Ce dépôt s'est déjà fait prendre par ce motif exact du côté des
prix.
"""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from app.ingestion.cnf import (
    RETAINED_NUTRIENT_CODES,
    parse_cnf_archive,
    parse_cnf_nutrients,
)
from app.services.fcen_measures import MeasureWeight
from app.services.nutrition_rules import parse_verified_unit_masses
from app.services.recipe_nutrition import NutrientFacts, NutritionIngredient

__all__ = [
    "ENERGY",
    "load_families",
    "load_food_groups",
    "load_measures",
    "load_foods",
    "load_ingredients",
    "load_recipes",
]

ENERGY, PROTEIN, FAT, CARBOHYDRATE = "208", "203", "204", "205"


def load_recipes(seed_dir: Path) -> list[dict]:
    return json.loads((seed_dir / "recipes.json").read_text(encoding="utf-8"))


def load_families(seed_dir: Path) -> dict[str, str]:
    """Nom lisible de chaque famille — le canon le porte, autant s'en servir."""
    path = seed_dir / "ingredient_families.json"
    if not path.exists():
        return {}
    return {
        row["id"]: row["name_fr"]
        for row in json.loads(path.read_text(encoding="utf-8"))
    }


def load_ingredients(
    seed_dir: Path, unit_curation: Path
) -> tuple[NutritionIngredient, ...]:
    rows = json.loads(
        (seed_dir / "canonical_ingredients.json").read_text(encoding="utf-8")
    )
    attached: dict[str, list[str]] = {}
    refs_path = seed_dir / "canonical_ingredient_external_refs.json"
    if refs_path.exists():
        for ref in json.loads(refs_path.read_text(encoding="utf-8")):
            if ref["source"] == "cnf":
                attached.setdefault(ref["canonical_ingredient_id"], []).append(
                    str(ref["external_id"])
                )
    masses = (
        parse_verified_unit_masses(
            json.loads(unit_curation.read_text(encoding="utf-8"))
        )
        if unit_curation.exists()
        else {}
    )
    return tuple(
        NutritionIngredient(
            ingredient_id=row["id"],
            name=row["name"],
            family_id=row.get("family_id"),
            base_unit=row["base_unit"],
            density_g_per_ml=(
                Decimal(str(row["density_g_per_ml"]))
                if row.get("density_g_per_ml") is not None
                else None
            ),
            grams_per_unit=masses.get(row["id"]),
            # Trié : le message d'ambiguïté cite toujours les mêmes codes dans
            # le même ordre, comme la façade SQL.
            food_codes=tuple(sorted(attached.get(row["id"], ()))),
        )
        for row in rows
    )


def load_foods(archive: Path) -> tuple[NutrientFacts, ...]:
    """Teneurs lues directement dans l'archive fédérale, sans passer par la base.

    Les rapports doivent tourner là où la base n'est pas — même promesse que
    l'audit de couverture des prix, qui se calcule sur des captures locales.
    """
    identity = _identity(str(archive))
    amounts: dict[str, dict[str, Decimal]] = {}
    for row in _nutrients(str(archive)).amounts:
        if row["nutrient_code"] in RETAINED_NUTRIENT_CODES:
            amounts.setdefault(row["food_code"], {})[row["nutrient_code"]] = (
                row["amount_per_100g"]
            )
    return tuple(
        NutrientFacts(
            food_code=food_code,
            food_name=identity.get(food_code, (f"aliment {food_code}", ""))[0],
            kcal_per_100g=values[ENERGY],
            protein_g_per_100g=values[PROTEIN],
            fat_g_per_100g=values[FAT],
            carbohydrate_g_per_100g=values[CARBOHYDRATE],
            source_version="2026",
        )
        for food_code, values in sorted(amounts.items())
        if all(code in values for code in RETAINED_NUTRIENT_CODES)
    )


def load_measures(archive: Path) -> dict[str, list[MeasureWeight]]:
    """Mesures domestiques du fichier fédéral, groupées par aliment."""
    by_food: dict[str, list[MeasureWeight]] = {}
    for row in _nutrients(str(archive)).measure_weights:
        by_food.setdefault(row["food_code"], []).append(
            MeasureWeight(
                food_code=row["food_code"],
                measure_type_code=row["measure_type_code"],
                measure_code=row["measure_code"],
                description=row["measure_description_fr"],
                grams=row["grams"],
            )
        )
    return by_food


def load_food_groups(archive: Path) -> dict[str, str]:
    """Groupe fédéral de chaque aliment — affiché, jamais interprété."""
    return {
        code: group for code, (_name, group) in _identity(str(archive)).items()
    }


# L'archive fait 26 Mo et deux appelants la lisent dans le même processus.
# Une seule lecture, mémorisée par chemin.
@lru_cache(maxsize=None)
def _identity(archive: str) -> dict[str, tuple[str, str]]:
    return {
        row["food_code"]: (
            row["food_description_fr"],
            row["cnf_food_group_description_fr"],
        )
        for row in parse_cnf_archive(Path(archive)).rows
    }


@lru_cache(maxsize=None)
def _nutrients(archive: str):
    return parse_cnf_nutrients(Path(archive))
