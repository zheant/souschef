"""Proposer des aliments FCÉN pour les ingrédients que le calcul ne résout pas.

Le script **propose**; il ne rattache rien. La décision reste humaine et passe
par l'action ``attach_existing`` du pipeline de curation, qui la journalise avec
son motif. Aucun rattachement automatique sur ressemblance : c'est la règle du
dépôt, et ce manifeste ne la contourne pas — il la rend tenable en réduisant
215 ingrédients à cinq candidats chacun, classés, avec les rejets motivés.

La file d'attente n'est pas alphabétique. Elle vient de l'audit de couverture,
donc du calcul lui-même : les ingrédients qui bloquent le plus de recettes
passent devant.

Exemple :
  python scripts/propose_cnf_matches.py --top 25
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

from app.services.cnf_match_proposal import (
    MatchFood,
    MatchTarget,
    propose_matches,
)
from app.services.nutrition_rules import parse_nutrition_rules
from app.services.recipe_nutrition import (
    AMBIGUOUS_CNF_FOOD,
    CHOSEN_FOOD_NOT_ATTACHED,
    NO_CNF_FOOD,
)
from app.services.recipe_nutrition_coverage import (
    audit_recipe_nutrition_coverage,
)
from nutrition_inputs import (
    load_families,
    load_food_groups,
    load_foods,
    load_ingredients,
    load_recipes,
)

#: Raisons de blocage qu'un appariement peut lever. Les autres relèvent d'un
#: autre chantier (masse par unité, densité, plafond de quantité) : les faire
#: figurer ici enverrait un curateur chercher un aliment qui existe déjà.
_MATCHABLE_REASONS = frozenset(
    {NO_CNF_FOOD, AMBIGUOUS_CNF_FOOD, CHOSEN_FOOD_NOT_ATTACHED}
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
        default=ROOT / "data" / "catalogue-reports" / "cnf-match-proposals.json",
        help=(
            "Manifeste écrit. Régénérable depuis le seed et l'archive, donc "
            "publié hors du dépôt par défaut; il porte de quoi être cité."
        ),
    )
    parser.add_argument("--limit", type=int, default=5, help="Candidats par ingrédient.")
    parser.add_argument("--top", type=int, default=25, help="Lignes affichées.")
    args = parser.parse_args()

    rules = parse_nutrition_rules(
        json.loads(args.rules.read_text(encoding="utf-8"))
    )
    recipes = load_recipes(args.seed_dir)
    ingredients = load_ingredients(args.seed_dir, args.unit_curation)
    foods = load_foods(args.archive)
    families = load_families(args.seed_dir)
    groups = load_food_groups(args.archive)
    catalogue = {row.ingredient_id: row for row in ingredients}

    audit = audit_recipe_nutrition_coverage(recipes, ingredients, foods, rules)
    targets = tuple(
        MatchTarget(
            ingredient_id=gap.canonical_ingredient_id,
            name=gap.name,
            family_name=families.get(
                catalogue[gap.canonical_ingredient_id].family_id or ""
            ),
            base_unit=gap.base_unit,
            blocked_recipes=gap.blocked_recipes,
            attached_food_codes=gap.attached_food_codes,
        )
        for gap in audit.gaps
        if gap.reason in _MATCHABLE_REASONS
        and gap.canonical_ingredient_id in catalogue
    )
    proposals = propose_matches(
        targets,
        [
            MatchFood(
                food_code=row.food_code,
                name=row.food_name,
                group=groups.get(row.food_code, ""),
                kcal_per_100g=row.kcal_per_100g,
            )
            for row in foods
        ],
        limit=args.limit,
    )

    manifest = {
        "proposal_version": "1",
        "source": "cnf",
        "source_version": "2026",
        "rules_version": rules.rule_version,
        "coverage": {
            "complete_recipes": audit.complete_recipes,
            "total_recipes": audit.total_recipes,
            "blocking_ingredients": audit.blocking_ingredients,
            "matchable_ingredients": len(targets),
        },
        "notes": [
            "Propositions, jamais des décisions : aucun rattachement",
            "automatique sur ressemblance. Chaque appariement retenu passe par",
            "l'action attach_existing, qui le journalise avec son motif.",
            "Les rejets sont publiés avec leur raison, jamais effacés.",
        ],
        "proposals": [row.as_dict() for row in proposals],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    _print_report(proposals, args.top, args.output, len(targets))
    return 0


def _print_report(proposals, top: int, output: Path, matchable: int) -> None:
    without = [row for row in proposals if not row.candidates]
    print(
        f"{matchable} ingrédients appariables — "
        f"{matchable - len(without)} avec au moins un candidat, "
        f"{len(without)} sans aucun."
    )
    print(f"Manifeste : {output}\n")
    print(f"Les {top} plus bloquants :")
    for row in proposals[:top]:
        best = row.candidates[0] if row.candidates else None
        head = (
            f"  {row.blocked_recipes:3} recettes  {row.ingredient_id:26}"
            f" « {row.ingredient_name[:26]:26} »"
        )
        if best is None:
            print(f"{head}  AUCUN CANDIDAT")
            continue
        print(
            f"{head}  → {best.food_code:>5} « {best.food_name[:52]:52} »"
            f" {best.kcal_per_100g!s:>7} kcal  {','.join(best.signals)}"
        )
    if without:
        print("\nSans aucun candidat — à traiter à la main ou par substitution :")
        for row in without:
            print(
                f"  {row.blocked_recipes:3} recettes  {row.ingredient_id:26}"
                f" « {row.ingredient_name[:40]} »"
            )


if __name__ == "__main__":
    raise SystemExit(main())
