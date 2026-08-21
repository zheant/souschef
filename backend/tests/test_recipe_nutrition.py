"""Une recette rend ses macros par portion, ou refuse en nommant ses trous.

Le module ne présente jamais un total partiel comme un total : dès qu'une ligne
n'est pas résolue, les quatre nombres sortent à `None` et la recette dit lesquels
de ses ingrédients l'en empêchent. Les lignes déclarées négligeables, elles,
comptent pour zéro et remontent la borne de l'erreur ainsi consentie.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.nutrition_rules import parse_nutrition_rules
from app.services.recipe_nutrition import (
    AMBIGUOUS_CNF_FOOD,
    CHOSEN_FOOD_ALREADY_ATTACHED,
    CHOSEN_FOOD_NOT_ATTACHED,
    COMPUTED,
    GAP,
    MISSING_DENSITY,
    MISSING_GRAMS_PER_UNIT,
    MISSING_NUTRIENT_VALUES,
    NEGLIGIBLE,
    NO_CNF_FOOD,
    OVER_NEGLIGIBLE_CEILING,
    NutrientFacts,
    NutritionIngredient,
    RecipeNutritionModule,
    UNKNOWN_INGREDIENT,
)
from app.services.recipe_scaling import RecipeNotScalableError


def facts(code="2388", kcal="86", protein="3.27", fat="1.18", carbs="19.02"):
    return NutrientFacts(
        food_code=code,
        food_name=f"Aliment {code}",
        kcal_per_100g=Decimal(kcal),
        protein_g_per_100g=Decimal(protein),
        fat_g_per_100g=Decimal(fat),
        carbohydrate_g_per_100g=Decimal(carbs),
        source_version="2026",
    )


def ingredient(
    iid="mais",
    base_unit="g",
    family_id="legumes",
    density=None,
    grams_per_unit=None,
    food_codes=("2388",),
):
    return NutritionIngredient(
        ingredient_id=iid,
        name=iid,
        family_id=family_id,
        base_unit=base_unit,
        density_g_per_ml=Decimal(density) if density else None,
        grams_per_unit=Decimal(grams_per_unit) if grams_per_unit else None,
        food_codes=tuple(food_codes),
    )


def recipe(rid="r1", servings=2, lines=(("mais", "200", "0"),)):
    return {
        "id": rid,
        "name": rid,
        "original_servings": servings,
        "ingredients": [
            {
                "canonical_ingredient_id": iid,
                "qty_fixed_per_batch_base_unit": fixed,
                "qty_marginal_per_serving_base_unit": marginal,
            }
            for iid, fixed, marginal in lines
        ],
    }


NO_RULES = parse_nutrition_rules({"rule_version": "test", "source_version": "2026"})


def one(recipes, ingredients, foods, rules=NO_RULES, **kwargs):
    return RecipeNutritionModule.facts_all(
        recipes, ingredients, foods, rules, **kwargs
    )[0]


def test_per_serving_is_the_fixed_part_divided_plus_the_marginal_part():
    result = one(
        [recipe(servings=4, lines=(("mais", "200", "10"),))],
        [ingredient()],
        [facts()],
    )
    # 200 g / 4 portions + 10 g = 60 g par portion, à 86 kcal/100 g.
    assert result.status == "complete"
    assert result.lines[0].grams_per_serving == Decimal("60")
    assert result.kcal_per_serving == Decimal("51.6")
    assert result.protein_g_per_serving == Decimal("2.0")
    assert result.kcal_error_bound_per_serving == Decimal("0")
    assert result.confidence == "exact"


def test_macros_are_summed_across_lines_not_only_energy():
    result = one(
        [recipe(lines=(("mais", "100", "0"), ("avocat", "100", "0")))],
        [ingredient(), ingredient("avocat", food_codes=("1511",))],
        [facts(), facts("1511", kcal="160", protein="2", fat="14.66", carbs="8.53")],
    )
    assert result.kcal_per_serving == Decimal("123.0")  # (86 + 160) × 50 g / 100
    assert result.fat_g_per_serving == Decimal("7.9")
    assert result.carbohydrate_g_per_serving == Decimal("13.8")


def test_an_uncurated_ingredient_refuses_the_whole_recipe_and_names_itself():
    result = one(
        [recipe(lines=(("mais", "100", "0"), ("bouillon_poulet", "500", "0")))],
        [ingredient(), ingredient("bouillon_poulet", "ml", "bouillons", food_codes=())],
        [facts()],
    )
    assert result.status == "incomplete"
    assert result.kcal_per_serving is None
    assert result.protein_g_per_serving is None
    assert result.confidence == "incomplete"
    assert result.missing == (("bouillon_poulet", NO_CNF_FOOD),)
    # La ligne calculable garde sa valeur : le refus porte sur le total, pas
    # sur la preuve. L'écran doit pouvoir montrer ce qui manque, et pourquoi.
    computed = [line for line in result.lines if line.resolution == COMPUTED]
    assert computed and computed[0].kcal is not None


def test_an_unknown_ingredient_is_a_gap_not_a_crash():
    result = one([recipe(lines=(("fantome", "10", "0"),))], [], [])
    assert result.missing == (("fantome", UNKNOWN_INGREDIENT),)


def test_a_food_without_nutrient_values_is_a_gap():
    result = one([recipe()], [ingredient()], [])
    assert result.missing == (("mais", MISSING_NUTRIENT_VALUES),)


def test_the_reason_reported_is_the_first_fact_the_calculation_needs():
    """Deux faits manquants : c'est celui qui bloque en premier qui est nommé.

    Une teneur absente et une densité absente sur la même ligne annonçaient
    « densité absente », alors que la curer n'aurait rien débloqué — la file de
    revue de l'audit pointait un travail inutile.
    """
    result = one(
        [recipe(lines=(("lait", "500", "0"),))],
        [ingredient("lait", "ml", "produits_laitiers", food_codes=("61",))],
        [],
    )
    assert result.missing == (("lait", MISSING_NUTRIENT_VALUES),)


NEGLIGIBLE_RULES = parse_nutrition_rules(
    {
        "rule_version": "test",
        "source_version": "2026",
        "negligible_contributions": [
            {
                "ingredient_id": "jus_lime",
                "base_unit": "ml",
                "kcal_per_100g": "25",
                "protein_g_per_100g": "0.42",
                "fat_g_per_100g": "0.23",
                "carbohydrate_g_per_100g": "8.42",
                "max_qty_per_serving_base_unit": "30",
                "grams_per_base_unit_ceiling": "1.05",
                "basis": "Jus d'agrume en assaisonnement.",
                "provenance": "FCÉN 2026, aliment 1594.",
            }
        ],
    }
)


def test_a_negligible_line_counts_for_zero_and_publishes_its_bound():
    result = one(
        [recipe(lines=(("mais", "100", "0"), ("jus_lime", "20", "0")))],
        [ingredient(), ingredient("jus_lime", "ml", "boissons", food_codes=())],
        [facts()],
        rules=NEGLIGIBLE_RULES,
    )
    assert result.status == "complete"
    # Le maïs seul porte le total : 50 g à 86 kcal/100 g.
    assert result.kcal_per_serving == Decimal("43.0")
    # 10 ml par portion × 1,05 g/ml × 25 kcal/100 g = 2,625 → borné à 2,7.
    assert result.kcal_error_bound_per_serving == Decimal("2.7")
    lime = [line for line in result.lines if line.ingredient_id == "jus_lime"][0]
    assert lime.resolution == NEGLIGIBLE
    assert lime.kcal == Decimal("0")
    assert "1594" in lime.detail
    # Les trois macros portent leur borne aussi : ne borner que l'énergie
    # laissait publier « 0,0 g de lipides » comme un fait mesuré.
    assert lime.fat_g_error_bound == Decimal("0.1")
    assert result.carbohydrate_g_error_bound_per_serving == Decimal("0.9")
    assert result.protein_g_error_bound_per_serving == Decimal("0.1")
    # Une borne consentie n'est pas une mesure : la recette le dit.
    assert result.confidence == "estimated"


def test_a_quantity_beyond_the_declared_ceiling_blocks_instead_of_absorbing():
    result = one(
        [recipe(servings=2, lines=(("jus_lime", "200", "0"),))],
        [ingredient("jus_lime", "ml", "boissons", food_codes=())],
        [],
        rules=NEGLIGIBLE_RULES,
    )
    assert result.status == "incomplete"
    assert result.missing == (("jus_lime", OVER_NEGLIGIBLE_CEILING),)
    line = result.lines[0]
    assert "100" in line.detail and "30" in line.detail


def test_a_volume_ingredient_needs_a_density_and_says_so_when_it_lacks_one():
    without = one(
        [recipe(lines=(("lait", "500", "0"),))],
        [ingredient("lait", "ml", "produits_laitiers", food_codes=("61",))],
        [facts("61", kcal="61")],
    )
    assert without.missing == (("lait", MISSING_DENSITY),)

    with_density = one(
        [recipe(lines=(("lait", "500", "0"),))],
        [
            ingredient(
                "lait", "ml", "produits_laitiers", density="1.03", food_codes=("61",)
            )
        ],
        [facts("61", kcal="61")],
    )
    # 250 ml par portion × 1,03 g/ml = 257,5 g, à 61 kcal/100 g.
    assert with_density.status == "complete"
    assert with_density.lines[0].grams_per_serving == Decimal("257.50")
    assert with_density.kcal_per_serving == Decimal("157.1")
    # Une conversion curée n'est pas une donnée publiée telle quelle.
    assert with_density.confidence == "audited_conversion"


def test_a_counted_ingredient_needs_a_curated_mass_per_unit():
    """`units.convert_qty` refuse count↔g; c'est ici que la masse curée entre.

    La règle du projet ne change pas : aucune conversion d'un compte vers une
    masse sans référentiel. Le module nutritionnel ne la contourne pas, il
    exige la masse curée et déclare le trou à défaut.
    """
    without = one(
        [recipe(lines=(("gousse_ail", "2", "0"),))],
        [ingredient("gousse_ail", "unit", "alliums", food_codes=("2394",))],
        [facts("2394", kcal="149")],
    )
    assert without.missing == (("gousse_ail", MISSING_GRAMS_PER_UNIT),)

    with_mass = one(
        [recipe(lines=(("gousse_ail", "2", "0"),))],
        [
            ingredient(
                "gousse_ail", "unit", "alliums", grams_per_unit="3",
                food_codes=("2394",),
            )
        ],
        [facts("2394", kcal="149")],
    )
    # 1 gousse par portion × 3 g, à 149 kcal/100 g.
    assert with_mass.lines[0].grams_per_serving == Decimal("3")
    assert with_mass.kcal_per_serving == Decimal("4.5")


AVOCADO_RULES = parse_nutrition_rules(
    {
        "rule_version": "test",
        "source_version": "2026",
        "food_choices": [
            {
                "ingredient_id": "avocat",
                "food_code": "1511",
                "kind": "primary",
                "rationale": "Le générique ne présume pas l'origine.",
                "provenance": "FCÉN 2026, aliment 1511.",
            }
        ],
    }
)


def test_several_attached_foods_are_ambiguous_until_one_is_declared():
    ambiguous = one(
        [recipe(lines=(("avocat", "200", "0"),))],
        [ingredient("avocat", food_codes=("1511", "1512", "1513"))],
        [facts("1511", kcal="160"), facts("1512", kcal="167"), facts("1513", kcal="120")],
    )
    assert ambiguous.missing == (("avocat", AMBIGUOUS_CNF_FOOD),)
    assert "1511" in ambiguous.lines[0].detail
    assert "1513" in ambiguous.lines[0].detail

    declared = one(
        [recipe(lines=(("avocat", "200", "0"),))],
        [ingredient("avocat", food_codes=("1511", "1512", "1513"))],
        [facts("1511", kcal="160"), facts("1512", kcal="167"), facts("1513", kcal="120")],
        rules=AVOCADO_RULES,
    )
    assert declared.status == "complete"
    assert declared.lines[0].food_code == "1511"
    assert declared.kcal_per_serving == Decimal("160.0")


def test_a_primary_choice_must_name_a_food_the_ingredient_actually_carries():
    """Un « primary » qui désigne un aliment non rattaché n'est pas un choix.

    C'est une correction ou une substitution — et celles-là portent un autre
    nom, et une justification écrite qui dit pourquoi le rattachement existant
    ne convient pas.
    """
    result = one(
        [recipe(lines=(("avocat", "200", "0"),))],
        [ingredient("avocat", food_codes=("1512", "1513"))],
        [facts("1511", kcal="160")],
        rules=AVOCADO_RULES,
    )
    assert result.missing == (("avocat", CHOSEN_FOOD_NOT_ATTACHED),)


def test_a_correction_may_name_a_food_the_ingredient_does_not_carry():
    rules = parse_nutrition_rules(
        {
            "rule_version": "test",
            "source_version": "2026",
            "food_choices": [
                {
                    "ingredient_id": "mais",
                    "food_code": "2388",
                    "kind": "correction",
                    "rationale": "Le canon est né de « Pâtes, maïs, sèches ».",
                    "provenance": "FCÉN 2026, aliment 2388.",
                }
            ],
        }
    )
    result = one(
        [recipe(lines=(("mais", "200", "0"),))],
        [ingredient("mais", food_codes=("4452",))],
        [facts("2388", kcal="86"), facts("4452", kcal="357")],
        rules=rules,
    )
    assert result.status == "complete"
    assert result.lines[0].food_code == "2388"
    assert result.kcal_per_serving == Decimal("86.0")
    assert "Pâtes" in result.lines[0].detail


def test_a_recipe_without_a_marginal_component_refuses_another_yield():
    with pytest.raises(RecipeNotScalableError):
        RecipeNutritionModule.facts_all(
            [recipe(servings=4, lines=(("mais", "200", "0"),))],
            [ingredient()],
            [facts()],
            NO_RULES,
            servings=6,
        )


def test_a_zero_quantity_line_is_neither_computed_nor_blocking():
    """Une exigence nulle ne bloque rien : il n'y a rien à chiffrer.

    Même arbitrage que le calcul de prix, qui produisait sinon une ligne
    d'achat à zéro unité et rendait le devis entier incomplet.
    """
    result = one(
        [recipe(lines=(("mais", "100", "0"), ("sel_table", "0", "0")))],
        [ingredient(), ingredient("sel_table", family_id="epices", food_codes=())],
        [facts()],
    )
    assert result.status == "complete"
    assert result.missing == ()


def test_the_serialised_form_keeps_the_refusal_visible():
    payload = one(
        [recipe(lines=(("bouillon_poulet", "500", "0"),))],
        [ingredient("bouillon_poulet", "ml", "bouillons", food_codes=())],
        [],
    ).as_dict()
    assert payload["status"] == "incomplete"
    assert payload["kcal_per_serving"] is None
    assert payload["fat_g_error_bound_per_serving"] is None
    assert payload["missing"] == [
        {"canonical_ingredient_id": "bouillon_poulet", "reason": NO_CNF_FOOD}
    ]
    assert payload["lines"][0]["resolution"] == GAP


ATTACHMENT_RULES = parse_nutrition_rules(
    {
        "rule_version": "test",
        "source_version": "2026",
        "food_choices": [
            {
                "ingredient_id": "farine_tout_usage",
                "food_code": "4595",
                "kind": "attachment",
                "rationale": (
                    "Le pont canonique a été curé pour l'identité commerciale "
                    "et n'a rien rattaché à cet ingrédient; le FCÉN publie "
                    "bien l'aliment."
                ),
                "provenance": "FCÉN 2026, aliment 4595 : 364 kcal/100 g.",
            }
        ],
    }
)


def test_an_attachment_retains_a_food_for_an_ingredient_the_bridge_left_empty():
    """Le cas de 189 des 198 bloquants : aucun aliment rattaché, aucun kind.

    « primary » est refusé (l'aliment n'est pas rattaché), « correction »
    suppose un rattachement qui nomme une autre classe, « substitution »
    suppose que le FCÉN ne publie pas l'aliment. Aucun des trois ne décrit un
    ingrédient que la curation d'identité a laissé vide.
    """
    result = one(
        [recipe(lines=(("farine_tout_usage", "200", "0"),))],
        [ingredient("farine_tout_usage", family_id="farines", food_codes=())],
        [facts("4595", kcal="364", protein="10.33", fat="0.98", carbs="76.31")],
        rules=ATTACHMENT_RULES,
    )
    assert result.status == "complete"
    assert result.lines[0].food_code == "4595"
    assert result.lines[0].kcal == Decimal("364.0")
    assert "attachment" in result.lines[0].detail


def test_an_attachment_is_refused_when_the_ingredient_already_carries_a_food():
    """Un ingrédient déjà rattaché relève de « primary » ou de « correction ».

    Sans ce refus, « attachment » deviendrait le kind fourre-tout qui dispense
    de dire pourquoi le rattachement existant ne convient pas.
    """
    result = one(
        [recipe(lines=(("farine_tout_usage", "200", "0"),))],
        [ingredient("farine_tout_usage", family_id="farines", food_codes=("4515",))],
        [facts("4595", kcal="364"), facts("4515", kcal="371")],
        rules=ATTACHMENT_RULES,
    )
    assert result.missing == (("farine_tout_usage", CHOSEN_FOOD_ALREADY_ATTACHED),)
    assert "4515" in result.lines[0].detail


def test_a_malformed_food_choice_is_never_absorbed_by_a_negligible_claim():
    """Une règle fautive doit remonter, même sur un ingrédient déclaré négligeable.

    Sans cet ordre, le recours d'apport négligeable répondait avant que la
    faute soit constatée : la recette sortait « complete » à 0 kcal et le
    règlement cassé n'était nommé nulle part. Neuf ingrédients du règlement
    livré sont dans cette position — déclarés négligeables *et* susceptibles de
    porter un choix d'aliment.
    """
    rules = parse_nutrition_rules(
        {
            "rule_version": "test",
            "source_version": "2026",
            "negligible_contributions": [
                {
                    "ingredient_id": "sel_table",
                    "base_unit": "g",
                    "kcal_per_100g": "0",
                    "protein_g_per_100g": "0",
                    "fat_g_per_100g": "0",
                    "carbohydrate_g_per_100g": "0",
                    "max_qty_per_serving_base_unit": "15",
                    "grams_per_base_unit_ceiling": "1",
                    "basis": "Le sel ne porte aucune énergie.",
                    "provenance": "FCÉN 2026, aliment 214.",
                }
            ],
            "food_choices": [
                {
                    "ingredient_id": "sel_table",
                    "food_code": "9999",
                    "kind": "primary",
                    "rationale": "Choix mal saisi : cet aliment n'est pas rattaché.",
                    "provenance": "FCÉN 2026, aliment 9999.",
                }
            ],
        }
    )
    result = one(
        [recipe(lines=(("sel_table", "5", "0"),))],
        [ingredient("sel_table", family_id="epices", food_codes=("1234",))],
        [facts("1234", kcal="0")],
        rules=rules,
    )
    assert result.status == "incomplete"
    assert result.missing == (("sel_table", CHOSEN_FOOD_NOT_ATTACHED),)
    assert result.lines[0].resolution == GAP
