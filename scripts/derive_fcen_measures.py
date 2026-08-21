"""Dériver du FCÉN la masse d'une unité et la densité — et publier les refus.

Deux chantiers, une seule source : les mesures domestiques du fichier fédéral
(type 6, mesures de service). Le script ne modifie aucun fichier de curation :
il propose, avec la provenance à recopier, et il dit pourquoi il renonce quand
il renonce — notamment devant une densité de tassement (250 ml de mozzarella
râpée pèsent 113 g, ce qui n'est pas une densité).

La dérivation vise **l'aliment que le calcul utilisera**, celui que le module
nutritionnel retient. Un ingrédient sans aliment retenu n'a pas de masse ni de
densité à dériver : c'est un appariement qui manque, pas une mesure.

Exemple :
  python scripts/derive_fcen_measures.py
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (str(BACKEND), str(Path(__file__).resolve().parent)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.services.fcen_measures import propose_density, propose_unit_mass
from app.services.nutrition_rules import parse_nutrition_rules
from app.services.recipe_nutrition import retained_food_code
from nutrition_inputs import (
    load_foods,
    load_ingredients,
    load_measures,
    load_recipes,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-dir", type=Path, default=ROOT / "seed" / "main")
    parser.add_argument(
        "--archive",
        type=Path,
        default=ROOT / "data" / "cnf_fcen_all-files-data_2026.zip",
    )
    parser.add_argument(
        "--rules", type=Path, default=ROOT / "config" / "nutrition-rules.json"
    )
    parser.add_argument(
        "--unit-curation",
        type=Path,
        default=ROOT / "config" / "cook_recipe_curation.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "catalogue-reports" / "fcen-measure-proposals.json",
    )
    args = parser.parse_args()

    rules = parse_nutrition_rules(
        json.loads(args.rules.read_text(encoding="utf-8"))
    )
    recipes = load_recipes(args.seed_dir)
    ingredients = load_ingredients(args.seed_dir, args.unit_curation)
    foods = {row.food_code: row for row in load_foods(args.archive)}
    measures = load_measures(args.archive)
    used = {
        line["canonical_ingredient_id"]
        for recipe in recipes
        for line in recipe["ingredients"]
    }

    masses, densities, unmatched = [], [], []
    for ingredient in ingredients:
        if ingredient.ingredient_id not in used:
            continue
        if ingredient.base_unit not in ("unit", "ml"):
            continue
        food_code = retained_food_code(ingredient, rules)
        if food_code is None or food_code not in foods:
            unmatched.append(ingredient)
            continue
        food = foods[food_code]
        rows = measures.get(food_code, [])
        if ingredient.base_unit == "unit":
            masses.append(
                propose_unit_mass(
                    ingredient.ingredient_id,
                    ingredient.name,
                    food_code,
                    food.food_name,
                    rows,
                )
            )
        else:
            densities.append(
                propose_density(
                    ingredient.ingredient_id,
                    food_code,
                    food.food_name,
                    rows,
                )
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "source": "cnf",
                "source_version": "2026",
                "unit_masses": [asdict(row) for row in masses],
                "densities": [asdict(row) for row in densities],
                "without_retained_food": [
                    {"ingredient_id": row.ingredient_id, "base_unit": row.base_unit}
                    for row in unmatched
                ],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"Ingrédients comptés ou en volume, utilisés par une recette : "
        f"{len(masses) + len(densities) + len(unmatched)}"
    )
    print(
        f"  avec aliment FCÉN retenu : {len(masses) + len(densities)}"
        f"  — sans : {len(unmatched)} (un appariement manque, pas une mesure)"
    )
    print(f"\nMasses par unité ({len(masses)}) :")
    for row in masses:
        verdict = (
            f"{row.grams_per_unit} g  « {row.measure_description} »"
            if row.grams_per_unit is not None
            else f"REFUS: {row.reason}"
        )
        print(f"  {row.ingredient_id:24} aliment {row.food_code:>5}  {verdict}")
    print(f"\nDensités ({len(densities)}) :")
    for row in densities:
        verdict = (
            f"{row.density_g_per_ml} g/ml"
            if row.density_g_per_ml is not None
            else f"REFUS: {row.reason}"
        )
        print(f"  {row.ingredient_id:24} aliment {row.food_code:>5}  {verdict}")
        if row.density_g_per_ml is None and row.examined:
            print(f"      examiné : {'; '.join(row.examined[:3])}")
    print(f"\nManifeste : {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
