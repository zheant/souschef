"""Audit déterministe de la couverture de prix, sans base de données."""

from decimal import Decimal

from app.services.recipe_pricing_coverage import (
    INCOMPATIBLE_PACKAGE_DIMENSION,
    MISSING_PRICE,
    NO_APPROVED_PRODUCT,
    PRICED,
    UNPARSED_OR_VARIABLE_PACKAGE,
    CoverageSupplyRule,
    ProductDecisionEvidence,
    audit_recipe_pricing_coverage,
)


def _recipe(recipe_id: str, *ingredients: str) -> dict:
    return {
        "id": recipe_id,
        "name": recipe_id,
        "ingredients": [
            {"canonical_ingredient_id": ingredient_id}
            for ingredient_id in ingredients
        ],
    }


def _decision(ingredient_id: str, status: str, reason: str, source="superc"):
    return ProductDecisionEvidence(source, status, ingredient_id, reason)


def test_audit_assigns_one_most_advanced_status_and_propagates_it_to_recipes():
    recipes = [
        _recipe("complete", "riz", "tomate"),
        _recipe("blocked", "tomate", "boeuf", "eau"),
    ]
    decisions = [
        _decision("riz", "matched", "human_approved"),
        _decision("tomate", "review", "package_not_fixed_or_unparsed"),
        _decision("tomate", "matched", "human_approved", source="maxi"),
        _decision("boeuf", "review", "package_not_fixed_or_unparsed"),
        _decision("boeuf", "review", "package_dimension_incompatible"),
    ]

    audit = audit_recipe_pricing_coverage(recipes, decisions)
    status = {row.canonical_ingredient_id: row.status for row in audit.ingredients}

    assert status == {
        "boeuf": INCOMPATIBLE_PACKAGE_DIMENSION,
        "eau": NO_APPROVED_PRODUCT,
        "riz": PRICED,
        "tomate": PRICED,
    }
    assert audit.complete_recipes == 1
    assert audit.recipes[1].missing == (
        ("boeuf", INCOMPATIBLE_PACKAGE_DIMENSION),
        ("eau", NO_APPROVED_PRODUCT),
    )


def test_price_is_the_last_gate_after_identity_package_and_dimension():
    audit = audit_recipe_pricing_coverage(
        [_recipe("soupe", "bouillon")],
        [
            _decision("bouillon", "review", "package_not_fixed_or_unparsed"),
            _decision("bouillon", "review", "package_dimension_incompatible"),
            _decision("bouillon", "review", "missing_or_invalid_price"),
        ],
    )

    assert audit.ingredients[0].status == MISSING_PRICE
    assert audit.ingredient_status_counts == {
        PRICED: 0,
        MISSING_PRICE: 1,
        INCOMPATIBLE_PACKAGE_DIMENSION: 0,
        UNPARSED_OR_VARIABLE_PACKAGE: 0,
        NO_APPROVED_PRODUCT: 0,
    }


def test_explicit_essential_and_derived_supply_rules_complete_recipes():
    recipes = [_recipe("omelette", "eau", "jaune_oeuf", "oeuf")]
    audit = audit_recipe_pricing_coverage(
        recipes,
        [_decision("oeuf", "matched", "human_approved")],
        supply_rules=[
            CoverageSupplyRule("eau", "essential"),
            CoverageSupplyRule("jaune_oeuf", "derived", "oeuf", Decimal("1")),
        ],
    )

    assert audit.complete_recipes == 1
    assert {row.canonical_ingredient_id: row.status for row in audit.ingredients} == {
        "eau": PRICED,
        "jaune_oeuf": PRICED,
        "oeuf": PRICED,
    }


def test_a_chain_of_derivations_resolves_like_the_costing_module_does():
    """Les deux lecteurs du même fichier doivent répondre la même chose.

    L'audit itérait jusqu'au point fixe pendant que le calcul de prix ne faisait
    qu'un seul saut : l'audit annonçait donc une couverture que le calcul ne
    savait pas livrer.
    """
    from app.services.recipe_costing import CostingOffer, RecipeCostingModule

    rules = [
        CoverageSupplyRule("jus_lime", "derived", "lime_pressee", Decimal("2")),
        CoverageSupplyRule("lime_pressee", "derived", "lime", Decimal("3")),
        CoverageSupplyRule("bouillon", "derived", "eau", Decimal("1")),
        CoverageSupplyRule("eau", "essential"),
    ]

    audit = audit_recipe_pricing_coverage(
        [_recipe("ceviche", "jus_lime", "bouillon")],
        [_decision("lime", "matched", "human_approved")],
        supply_rules=rules,
    )
    assert audit.complete_recipes == 1

    quote = RecipeCostingModule.quote_all(
        [
            {
                "id": "ceviche", "name": "Ceviche", "original_servings": 2,
                "ingredients": [
                    {
                        "canonical_ingredient_id": ingredient_id,
                        "qty_fixed_per_batch_base_unit": "10",
                        "qty_marginal_per_serving_base_unit": "0",
                    }
                    for ingredient_id in ("jus_lime", "bouillon")
                ],
            }
        ],
        [CostingOffer("lime-1", "lime", "s", Decimal("1"), 79)],
        supply_rules=rules,
    )[0]
    assert quote.status == "complete"
    assert quote.incomplete_ingredients == ()


def test_a_derived_rule_without_a_ratio_resolves_for_neither_reader():
    audit = audit_recipe_pricing_coverage(
        [_recipe("sauce", "jaune_oeuf")],
        [_decision("oeuf", "matched", "human_approved")],
        supply_rules=[CoverageSupplyRule("jaune_oeuf", "derived", "oeuf")],
    )

    assert audit.complete_recipes == 0


def test_derived_supply_rule_remains_blocked_when_its_source_is_unpriced():
    audit = audit_recipe_pricing_coverage(
        [_recipe("sauce", "jaune_oeuf")],
        [],
        supply_rules=[CoverageSupplyRule("jaune_oeuf", "derived", "oeuf", Decimal("1"))],
    )

    assert audit.complete_recipes == 0
    assert audit.ingredients[0].status == NO_APPROVED_PRODUCT
