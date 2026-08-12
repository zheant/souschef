"""Évaluateur pur de l'équation de couverture — besoins par ingrédient d'un
menu résolu (â^marg·x + â^fixe·δ si le mécanisme de lot est actif).

Utilisé par ``services/planning.py::_persist_plan`` pour peupler
``Plan.ingredient_needs`` à la génération/réoptimisation — c'est ce que
``_needed_ingredients`` (écran de confirmation post-génération) et
``_grocery_list`` (association ingrédient → recettes consommatrices)
lisent ensuite pour l'affichage. Le commit (pilote, docs/product-pilot.md,
depuis le retrait du garde-manger) et le diagnostic du solveur n'en ont
plus besoin — les deux anciens usages qui justifiaient ce module ont été
retirés avec le garde-manger."""

from __future__ import annotations

from decimal import Decimal

from .problem_data import ProblemData


def ingredient_needs(
    problem: ProblemData,
    servings: dict[str, int],
    cooked: dict[str, bool],
    include_fixed: bool,
) -> dict[str, Decimal]:
    needs: dict[str, Decimal] = {}
    for r in problem.recipes:
        x = servings.get(r.id, 0)
        delta = cooked.get(r.id, x > 0)
        if x == 0 and not (include_fixed and delta):
            continue
        for ri in r.ingredients:
            q = ri.qty_marginal_per_serving_base_unit * x
            if include_fixed and delta:
                q += ri.qty_fixed_per_batch_base_unit
            if q > 0:
                needs[ri.canonical_ingredient_id] = (
                    needs.get(ri.canonical_ingredient_id, Decimal(0)) + q
                )
    return needs
