"""L'audit lit les trous du calcul, et classe la curation par effet mesuré.

Deux propriétés valent des tests : l'audit ne peut pas répondre autrement que
le calcul (il l'appelle), et la courbe de déblocage est celle des recettes
complétées, pas celle des ingrédients les plus fréquents. La seconde n'est pas
un détail de présentation : c'est l'ordre dans lequel un humain va passer ses
sessions de revue.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.nutrition_rules import parse_nutrition_rules
from app.services.recipe_nutrition import (
    NO_CNF_FOOD,
    NutrientFacts,
    NutritionIngredient,
)
from app.services.recipe_nutrition_coverage import (
    audit_recipe_nutrition_coverage,
    suspect_food_name,
)

RULES = parse_nutrition_rules({"rule_version": "audit-test", "source_version": "2026"})


def ingredient(iid, food_codes=(), base_unit="g", name=None):
    return NutritionIngredient(
        ingredient_id=iid,
        name=name or iid,
        family_id="legumes",
        base_unit=base_unit,
        density_g_per_ml=None,
        grams_per_unit=None,
        food_codes=tuple(food_codes),
    )


def facts(code, name="Aliment", kcal="100"):
    return NutrientFacts(
        food_code=code,
        food_name=name,
        kcal_per_100g=Decimal(kcal),
        protein_g_per_100g=Decimal("1"),
        fat_g_per_100g=Decimal("1"),
        carbohydrate_g_per_100g=Decimal("1"),
        source_version="2026",
    )


def recipe(rid, ingredient_ids):
    return {
        "id": rid,
        "name": rid,
        "original_servings": 2,
        "ingredients": [
            {
                "canonical_ingredient_id": iid,
                "qty_fixed_per_batch_base_unit": "100",
                "qty_marginal_per_serving_base_unit": "0",
            }
            for iid in ingredient_ids
        ],
    }


def test_the_audit_counts_the_same_gaps_the_calculation_refuses_on():
    audit = audit_recipe_nutrition_coverage(
        [recipe("r1", ["mais", "bouillon"]), recipe("r2", ["mais"])],
        [ingredient("mais", ["2388"]), ingredient("bouillon")],
        [facts("2388")],
        RULES,
    )
    assert audit.total_recipes == 2
    assert audit.complete_recipes == 1
    assert audit.blocking_ingredients == 1
    assert audit.gaps[0].canonical_ingredient_id == "bouillon"
    assert audit.gaps[0].reason == NO_CNF_FOOD
    assert audit.gaps[0].blocked_recipes == 1
    assert audit.gap_reason_counts == {NO_CNF_FOOD: 1}
    assert audit.computed_lines == 2
    assert audit.rule_version == "audit-test"


def test_the_unlock_curve_orders_by_recipes_completed_not_by_frequency():
    """Un ingrédient fréquent qui ne complète rien seul ne passe pas devant.

    ``commun`` bloque trois recettes, ``rare`` une seule. Le classement par
    fréquence commencerait par ``commun`` sans rien rendre calculable, puisque
    ses trois recettes ont chacune un second trou. La recette la moins chère à
    compléter est celle de ``rare``.
    """
    audit = audit_recipe_nutrition_coverage(
        [
            recipe("r1", ["commun", "propre_1"]),
            recipe("r2", ["commun", "propre_2"]),
            recipe("r3", ["commun", "propre_3"]),
            recipe("r4", ["rare"]),
        ],
        [
            ingredient(iid)
            for iid in ("commun", "propre_1", "propre_2", "propre_3", "rare")
        ],
        [],
        RULES,
    )
    # Le plus fréquent reste rapporté comme tel — les deux lectures coexistent.
    assert audit.gaps[0].canonical_ingredient_id == "commun"
    assert audit.gaps[0].blocked_recipes == 3

    first = audit.unlock_curve[0]
    assert first.recipe_id == "r4"
    assert first.added_ingredient_ids == ("rare",)
    assert first.cumulative_ingredients == 1
    assert first.recipes_computable == 1

    # Une fois `commun` payé avec la première recette qui l'exige, les deux
    # suivantes ne coûtent qu'un ingrédient chacune.
    assert [step.cumulative_ingredients for step in audit.unlock_curve] == [1, 3, 4, 5]
    assert [step.recipes_computable for step in audit.unlock_curve] == [1, 2, 3, 4]
    assert audit.ingredients_for_full_coverage == 5


def test_a_recipe_already_computable_costs_nothing_and_comes_first():
    audit = audit_recipe_nutrition_coverage(
        [recipe("libre", ["mais"]), recipe("bloquee", ["mais", "bouillon"])],
        [ingredient("mais", ["2388"]), ingredient("bouillon")],
        [facts("2388")],
        RULES,
    )
    assert audit.unlock_curve[0].recipe_id == "libre"
    assert audit.unlock_curve[0].added_ingredient_ids == ()
    assert audit.unlock_curve[0].cumulative_ingredients == 0


def test_the_audit_publishes_the_pairings_it_actually_computed_from():
    """La carte des appariements est le seul moyen de relire un pont curé.

    Elle est classée par nombre de recettes touchées : relire d'abord ce qui
    porte le plus de chiffres.
    """
    audit = audit_recipe_nutrition_coverage(
        [
            recipe("r1", ["mais", "tomate_conserve"]),
            recipe("r2", ["tomate_conserve"]),
        ],
        [
            ingredient("mais", ["4452"], name="Maïs"),
            ingredient("tomate_conserve", ["2257"], name="Tomate en conserve"),
        ],
        [
            facts("4452", "Pâtes, maïs, sèches", "357"),
            facts("2257", "Tomate, rouge, mûre, conserve", "15"),
        ],
        RULES,
    )
    assert [row.canonical_ingredient_id for row in audit.retained_foods] == [
        "tomate_conserve",
        "mais",
    ]
    assert audit.retained_foods[0].recipe_occurrences == 2
    assert audit.retained_foods[1].food_name == "Pâtes, maïs, sèches"
    assert audit.retained_foods[1].kcal_per_100g == Decimal("357")
    # « Pâtes, maïs, sèches » partage le mot « maïs » : ce n'est pas un
    # désaccord franc, et l'audit ne prétend pas le trancher.
    assert audit.suspect_foods == ()


def test_a_frank_mismatch_is_flagged_and_a_shared_word_is_not():
    # Le premier segment fédéral est souvent une classe, pas un démenti.
    assert not suspect_food_name("Aneth frais", "Épices, aneth, frais")
    assert not suspect_food_name("Maïs", "Maïs sucré, jaune, cru")
    assert not suspect_food_name("Maïs", "Pâtes, maïs, sèches")
    # Les pluriels ne comptent pas pour un désaccord.
    assert not suspect_food_name("Asperges", "Asperge, crue")
    assert not suspect_food_name("Poireau", "Poireaux, crus")
    # Rien en commun : là, il y a de quoi relire.
    assert suspect_food_name("Ketchup", "Sauce, tomate, conserve")
    # Rien de significatif à comparer : l'audit se tait plutôt que de crier.
    assert not suspect_food_name("Ail", "Ail, cru")


def test_the_serialised_audit_carries_the_summary_the_script_prints():
    payload = audit_recipe_nutrition_coverage(
        [recipe("r1", ["mais", "bouillon"])],
        [ingredient("mais", ["2388"]), ingredient("bouillon")],
        [facts("2388")],
        RULES,
    ).as_dict()
    assert payload["summary"]["complete_recipes"] == 0
    assert payload["summary"]["ingredients_for_full_coverage"] == 1
    assert payload["gaps"][0]["canonical_ingredient_id"] == "bouillon"
    assert payload["recipes"][0]["missing"] == [
        {"canonical_ingredient_id": "bouillon", "reason": NO_CNF_FOOD}
    ]
