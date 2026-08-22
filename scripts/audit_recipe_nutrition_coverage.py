"""Auditer la couverture nutritionnelle des recettes, sans base de données.

Le rapport répond à une seule question : dans quel ordre curer pour que des
recettes deviennent calculables. Il lit le seed versionné, le règlement
nutritionnel et l'archive fédérale — rien d'autre — et appelle le module de
calcul pour que la définition d'un « trou » soit exactement la sienne.

Exemple :
  python scripts/audit_recipe_nutrition_coverage.py \
    --archive data/cnf_fcen_all-files-data_2026.zip \
    --json-output data/catalogue-reports/nutrition-coverage.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.nutrition_rules import parse_nutrition_rules
from app.services.recipe_nutrition_coverage import (
    audit_recipe_nutrition_coverage,
)
from nutrition_inputs import load_foods, load_ingredients, load_recipes


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
    parser.add_argument("--json-output", type=Path)
    parser.add_argument(
        "--top", type=int, default=20, help="Lignes de détail affichées."
    )
    parser.add_argument(
        "--minimum-complete-recipes",
        type=int,
        help="Sort en erreur si moins de recettes que ça sont calculables.",
    )
    args = parser.parse_args()

    rules = parse_nutrition_rules(
        json.loads(args.rules.read_text(encoding="utf-8"))
    )
    recipes = load_recipes(args.seed_dir)
    ingredients = load_ingredients(args.seed_dir, args.unit_curation)
    foods = load_foods(args.archive)

    audit = audit_recipe_nutrition_coverage(recipes, ingredients, foods, rules)
    payload = audit.as_dict()
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    _print_report(audit, args.top)

    minimum = args.minimum_complete_recipes
    if minimum is not None and audit.complete_recipes < minimum:
        print(
            f"ÉCHEC: {audit.complete_recipes} recettes calculables, "
            f"minimum {minimum}.",
            file=sys.stderr,
        )
        return 1
    return 0


def _print_report(audit, top: int) -> None:
    print(
        f"Recettes calculables: {audit.complete_recipes}/{audit.total_recipes}"
        f"  (règlement {audit.rule_version})"
    )
    print(
        f"Ingrédients cités: {audit.total_recipe_ingredients} — "
        f"bloquants: {audit.blocking_ingredients} — "
        f"à curer pour tout couvrir: {audit.ingredients_for_full_coverage}"
    )
    print(
        f"Lignes calculées: {audit.computed_lines} — "
        f"déclarées négligeables: {audit.negligible_lines}"
    )
    print("\nRaisons de blocage:")
    for reason, count in audit.gap_reason_counts.items():
        print(f"  {reason:28} {count}")

    print(f"\nBloquants par recettes touchées (les {top} premiers):")
    for gap in audit.gaps[:top]:
        print(
            f"  {gap.blocked_recipes:3} recettes  {gap.canonical_ingredient_id:28}"
            f" {gap.reason:26} {gap.base_unit:4}"
            f" {'refs=' + ','.join(gap.attached_food_codes) if gap.attached_food_codes else ''}"
        )

    print("\nCourbe de déblocage (curation par recettes complétées):")
    print("  ingrédients curés → recettes calculables")
    shown = 0
    for step in audit.unlock_curve:
        # Une étape qui ne coûte rien ne dit rien de neuf : on n'imprime que
        # celles qui font avancer la file.
        if step.added_ingredient_ids or step.rank == 1:
            shown += 1
            if shown <= top or step.rank == len(audit.unlock_curve):
                print(
                    f"  {step.cumulative_ingredients:4} → "
                    f"{step.recipes_computable:4}   +"
                    f"{','.join(step.added_ingredient_ids) or '(rien)':60.60}"
                    f" [{step.recipe_id[:38]}]"
                )

    print(
        f"\nAppariements retenus, à relire ({len(audit.retained_foods)}, "
        f"les {top} plus cités):"
    )
    for retained in audit.retained_foods[:top]:
        print(
            f"  {retained.recipe_occurrences:3}×  "
            f"{retained.canonical_ingredient_id:26} "
            f"{retained.kcal_per_100g:>8} kcal/100 g  "
            f"« {retained.food_name[:56]} »"
        )

    if audit.suspect_foods:
        print(
            f"\nDésaccords francs — aucun mot commun entre les deux noms "
            f"({len(audit.suspect_foods)}):"
        )
        for suspect in audit.suspect_foods:
            print(
                f"  {suspect.canonical_ingredient_id:26} "
                f"« {suspect.ingredient_name} » → {suspect.food_code} "
                f"« {suspect.food_name[:52]} »"
            )


if __name__ == "__main__":
    raise SystemExit(main())
