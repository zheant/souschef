"""Écrire dans le règlement les aliments FCÉN retenus, décision par décision.

Le manifeste de `propose_cnf_matches.py` propose; ce script écrit ce qu'une
relecture a tranché. La provenance de chaque entrée est rendue depuis les
teneurs publiées par l'archive — jamais saisie — et le titre de la décision est
confronté au pont canonique → FCÉN avant écriture.

Le fichier de décisions est une liste d'objets :

  [{"ingredient_id": "farine_tout_usage", "food_code": "4484",
    "kind": "attachment", "rationale": "…"}]

Exemple :
  python scripts/declare_food_choices.py --decisions lot-cereales.json \
    --rule-version 2026-08-21a
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (str(BACKEND), str(Path(__file__).resolve().parent)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.services.food_choice_ledger import (
    FoodChoiceDecision,
    FoodChoiceRefused,
    merge_food_choices,
    render_food_choices,
)
from app.services.nutrition_rules import (
    NutritionRulesInvalid,
    parse_nutrition_rules,
)
from nutrition_inputs import load_foods, load_ingredients


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", required=True, type=Path)
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
        "--rule-version",
        required=True,
        help=(
            "Version que porte le règlement après écriture. Un chiffre publié "
            "cite une version; ajouter des entrées sans la changer ferait dire "
            "deux choses à un même nom."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    decisions = [
        FoodChoiceDecision(
            ingredient_id=row["ingredient_id"],
            food_code=str(row["food_code"]),
            kind=row["kind"],
            rationale=row["rationale"],
        )
        for row in json.loads(args.decisions.read_text(encoding="utf-8"))
    ]
    foods = {row.food_code: row for row in load_foods(args.archive)}
    attached = {
        row.ingredient_id: row.food_codes
        for row in load_ingredients(args.seed_dir, args.unit_curation)
    }
    rules = json.loads(args.rules.read_text(encoding="utf-8"))

    if args.rule_version == rules.get("rule_version"):
        print(
            f"Refusé : le règlement porte déjà la version "
            f"{args.rule_version!r}. Ajouter des entrées sous un nom déjà "
            "publié ferait dire deux choses au même nom — c'est ce que "
            "cette option existe pour empêcher.",
            file=sys.stderr,
        )
        return 1

    try:
        entries = render_food_choices(decisions, foods, attached)
        merged = merge_food_choices(rules.get("food_choices", []), entries)
    except FoodChoiceRefused as error:
        print(f"Refusé : {error}", file=sys.stderr)
        return 1

    rules["food_choices"] = merged
    rules["rule_version"] = args.rule_version

    # Relire ce qu'on va écrire, avant de l'écrire. Le grand livre contrôle
    # ce que le parseur ne peut pas voir (le pont canonique), et le parseur
    # contrôle ce que le grand livre ne connaît pas (la forme du fichier
    # entier). Écrire d'abord et découvrir ensuite, c'était livrer un
    # règlement illisible et une API en 503 sur toutes les recettes.
    try:
        parse_nutrition_rules(rules)
    except NutritionRulesInvalid as error:
        print(f"Refusé (le règlement fusionné ne se relit pas) : {error}",
              file=sys.stderr)
        return 1
    encoded = json.dumps(rules, ensure_ascii=False, indent=2) + "\n"
    if not args.dry_run:
        args.rules.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {
                "written": None if args.dry_run else str(args.rules),
                "rule_version": args.rule_version,
                "added": len(entries),
                "food_choices": len(merged),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
