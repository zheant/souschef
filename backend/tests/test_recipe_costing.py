from decimal import Decimal

import pytest

from app.services.recipe_costing import (
    CostingOffer,
    RecipeCostingModule,
    RecipeNotScalableError,
    SupplyRule,
)


def _recipe(*ingredients):
    return {
        "id": "soupe",
        "name": "Soupe test",
        "original_servings": 4,
        "ingredients": [
            {
                "canonical_ingredient_id": ingredient_id,
                "qty_fixed_per_batch_base_unit": fixed,
                "qty_marginal_per_serving_base_unit": marginal,
            }
            for ingredient_id, fixed, marginal in ingredients
        ],
    }


def test_fixed_package_reports_consumed_checkout_and_promotion():
    quote = RecipeCostingModule.quote_all(
        [_recipe(("tomate", "0", "100"))],
        [
            CostingOffer(
                "tomates-796",
                "tomate",
                "superc_640",
                Decimal("796"),
                199,
                regular_price_cents_cad=249,
                is_promo=True,
                valid_from="2026-08-13",
                valid_to="2026-08-19",
            )
        ],
    )[0]

    assert quote.status == "complete"
    assert quote.consumed_cost_cents == Decimal("100.00")
    assert quote.consumed_cost_per_serving_cents == Decimal("25.00")
    assert quote.autonomous_checkout_cents == Decimal("199.00")
    assert quote.regular_comparable_cents == Decimal("249.00")
    assert quote.promotional_savings_cents == Decimal("50.00")


def test_derived_requirements_share_parent_before_rounding():
    quote = RecipeCostingModule.quote_all(
        [_recipe(("jus_citron", "20", "0"), ("zeste_citron", "1", "0"))],
        [CostingOffer("citron-un", "citron", "maxi_7552", Decimal("1"), 75)],
        supply_rules=[
            SupplyRule(
                "jus_citron",
                "derived",
                "citron",
                Decimal("0.5"),
                provenance="conversion test jus",
            ),
            SupplyRule("zeste_citron", "derived", "citron", Decimal("0.5")),
        ],
    )[0]

    assert len(quote.purchases) == 1
    assert quote.purchases[0].required_quantity == Decimal("10.5")
    assert quote.purchases[0].purchase_units == Decimal("11")
    assert quote.autonomous_checkout_cents == Decimal("825.00")
    assert quote.consumed_confidence == "audited_conversion"
    assert quote.ingredients[0].reason == "conversion test jus"


def test_variable_weight_without_increment_is_declared_estimated():
    quote = RecipeCostingModule.quote_all(
        [_recipe(("boeuf", "0", "125"))],
        [
            CostingOffer(
                "boeuf-kg",
                "boeuf",
                "superc_640",
                Decimal("1000"),
                1651,
                sale_mode="variable_weight",
            )
        ],
    )[0]

    assert quote.consumed_cost_cents == Decimal("825.50")
    # Le décaissement seul est estimé: l'ADR ne dégrade que lui, pas la
    # valorisation au prix unitaire, qui reste exacte.
    assert quote.consumed_confidence == "exact"
    assert quote.checkout_confidence == "estimated"


def test_consumption_is_valued_at_the_price_of_the_product_actually_bought():
    """Le format le moins cher à l'unité est le plus gros du magasin.

    Un sac de 50 lb de pommes de terre bat n'importe quel petit format au 100 g,
    mais personne ne l'achète pour 600 g de besoin. Le panier prend donc le sac
    de 2 kg — et la valorisation le suit.

    Elle prenait auparavant le meilleur prix unitaire du magasin, donc le sac de
    50 lb : sur le rapport W33, 532 lignes étaient valorisées sur un produit
    autre que celui acheté, et le total sortait 9,9 % sous le prix de tout
    panier réel. Le meilleur prix unitaire reste publié à côté, sans prétendre
    être ce qu'on paie.
    """
    quote = RecipeCostingModule.quote_all(
        [_recipe(("pomme_de_terre", "600", "0"))],
        [
            CostingOffer(
                "patates-50lb", "pomme_de_terre", "superc_640", Decimal("22680"), 1999
            ),
            CostingOffer(
                "patates-2kg", "pomme_de_terre", "superc_640", Decimal("2000"), 399
            ),
        ],
    )[0]

    # 600 g au prix du sac de 2 kg (0,20 $/100 g), celui qu'on achète vraiment.
    assert quote.consumed_cost_cents == Decimal("119.70")
    assert quote.ingredients[0].product_external_key == "patates-2kg"
    # Le sac de 50 lb reste la référence « au mieux », à 0,09 $/100 g.
    assert quote.best_unit_price_cents == Decimal("52.88")
    # Et le panier paie un seul sac de 2 kg, pas 19,99 $.
    assert quote.purchases[0].product_external_key == "patates-2kg"
    assert quote.purchases[0].purchase_units == Decimal("1")
    assert quote.autonomous_checkout_cents == Decimal("399.00")


def test_a_basket_is_composed_in_one_store():
    """Un décaissement autonome décrit une course, pas une tournée."""
    quote = RecipeCostingModule.quote_all(
        [_recipe(("riz", "500", "0"), ("boeuf", "400", "0"))],
        [
            CostingOffer("riz-a", "riz", "maxi_7552", Decimal("900"), 300),
            CostingOffer("riz-b", "riz", "superc_640", Decimal("900"), 349),
            CostingOffer("boeuf-a", "boeuf", "maxi_7552", Decimal("500"), 999),
            CostingOffer("boeuf-b", "boeuf", "superc_640", Decimal("500"), 899),
        ],
    )[0]

    # maxi: 3,00 + 9,99 = 12,99 ; superc: 3,49 + 8,99 = 12,48 -> superc.
    assert quote.stores == ("superc_640",)
    assert quote.basket_scope == "single_store"
    assert quote.autonomous_checkout_cents == Decimal("1248.00")


def test_the_no_promo_reference_shops_in_the_same_store_as_the_basket():
    """Sinon on compare une course à une tournée.

    Le panier payé est restreint au magasin retenu, mais la référence « prix
    régulier » balayait tous les magasins : elle profitait d'une bannière que le
    panier n'a pas le droit de visiter, et l'économie annoncée était celle d'un
    panier que personne ne peut faire.
    """
    quote = RecipeCostingModule.quote_all(
        [_recipe(("tomate", "800", "0"))],
        [
            CostingOffer(
                "chez-nous", "tomate", "superc_640", Decimal("800"), 300,
                regular_price_cents_cad=500, is_promo=True,
            ),
            # Moins cher au régulier, mais dans une bannière que le panier ne
            # visite pas: il ne doit pas servir de référence.
            CostingOffer("ailleurs", "tomate", "maxi_7552", Decimal("800"), 350),
        ],
    )[0]

    assert quote.stores == ("superc_640",)
    assert quote.autonomous_checkout_cents == Decimal("300.00")
    assert quote.regular_comparable_cents == Decimal("500.00")
    assert quote.promotional_savings_cents == Decimal("200.00")


def test_a_basket_no_single_store_can_fill_says_so():
    quote = RecipeCostingModule.quote_all(
        [_recipe(("riz", "500", "0"), ("boeuf", "400", "0"))],
        [
            CostingOffer("riz-a", "riz", "maxi_7552", Decimal("900"), 349),
            CostingOffer("boeuf-b", "boeuf", "superc_640", Decimal("500"), 899),
        ],
    )[0]

    assert quote.basket_scope == "multi_store"
    assert quote.stores == ("maxi_7552", "superc_640")


def test_missing_product_never_becomes_zero_cost():
    quote = RecipeCostingModule.quote_all(
        [_recipe(("introuvable", "0", "10"))], []
    )[0]

    assert quote.status == "incomplete"
    assert quote.consumed_cost_cents is None
    assert quote.autonomous_checkout_cents is None
    assert quote.incomplete_ingredients == ("introuvable",)


def test_asking_for_other_servings_is_refused_when_the_recipe_cannot_scale():
    """121 des 161 recettes n'ont aucune composante marginale par portion.

    Toutes les recettes importées portent leurs quantités dans la composante
    fixe par lot. Demander 8 portions renvoyait la même nourriture, le même
    panier et le même total; seule la division par portion changeait. L'appelant
    n'avait aucun moyen de le savoir.
    """
    with pytest.raises(RecipeNotScalableError) as error:
        RecipeCostingModule.quote_all(
            [_recipe(("riz", "500", "0"))],
            [CostingOffer("riz", "riz", "s", Decimal("1000"), 500)],
            servings=8,
        )
    assert "soupe" in str(error.value)


def test_its_own_serving_count_is_always_allowed():
    """Le rendement publié n'est pas un rescalage: il ne demande rien de neuf."""
    quote = RecipeCostingModule.quote_all(
        [_recipe(("riz", "500", "0"))],
        [CostingOffer("riz", "riz", "s", Decimal("1000"), 500)],
        servings=4,
    )[0]
    assert quote.servings == 4


def test_a_recipe_with_a_marginal_component_scales_normally():
    quote = RecipeCostingModule.quote_all(
        [_recipe(("riz", "100", "50"))],
        [CostingOffer("riz", "riz", "s", Decimal("1000"), 500)],
        servings=8,
    )[0]
    assert quote.ingredients[0].required_quantity == Decimal("500")


def test_a_weight_purchase_is_rounded_to_something_a_counter_can_weigh():
    """« Acheter 0,003 kg d'ail » n'existe pas en caisse.

    Un produit au poids sans incrément publié laissait acheter une fraction
    arbitraire du format de référence, avec trente décimales dans le rapport.
    """
    quote = RecipeCostingModule.quote_all(
        [_recipe(("ail", "3", "0"))],
        [
            CostingOffer(
                "ail-kg", "ail", "s", Decimal("1000"), 1541, sale_mode="variable_weight"
            )
        ],
    )[0]
    line = quote.purchases[0]

    assert line.purchase_units == Decimal("0.01")  # 10 g, pas 3 g
    assert line.purchased_quantity == Decimal("10.00")
    assert line.checkout_cost_cents == Decimal("15.41")
    assert quote.checkout_confidence == "estimated"


def test_published_purchase_units_carry_no_trailing_decimals():
    quote = RecipeCostingModule.quote_all(
        [_recipe(("boeuf", "333", "0"))],
        [
            CostingOffer(
                "boeuf-kg", "boeuf", "s", Decimal("1000"), 1651,
                sale_mode="variable_weight",
            )
        ],
    )[0]

    assert str(quote.purchases[0].purchase_units) == "0.34"


def test_an_unknown_sale_mode_is_refused_not_smoothed_over():
    """Une faute de frappe en curation devenait un décaissement plausible.

    Toute valeur inconnue tombait dans la branche « acheter exactement le
    besoin » et se contentait d'abaisser la confiance.
    """
    with pytest.raises(ValueError) as error:
        RecipeCostingModule.quote_all(
            [_recipe(("truc", "150", "0"))],
            [CostingOffer("x", "truc", "s", Decimal("1000"), 500, sale_mode="mode_inconnu")],
        )
    assert "mode_inconnu" in str(error.value)


def test_disjoint_validity_windows_never_publish_an_impossible_period():
    """max(débuts) et min(fins) produisaient une fenêtre vide, publiée telle quelle."""
    quote = RecipeCostingModule.quote_all(
        [_recipe(("a", "10", "0"), ("b", "10", "0"))],
        [
            CostingOffer(
                "a1", "a", "s", Decimal("100"), 100,
                valid_from="2026-08-13", valid_to="2026-08-19",
            ),
            CostingOffer(
                "b1", "b", "s", Decimal("100"), 100,
                valid_from="2026-08-20", valid_to="2026-08-26",
            ),
        ],
    )[0]

    assert quote.valid_from is None
    assert quote.valid_to is None
    assert quote.validity_reason == "no_common_validity_window"


def test_a_common_window_is_still_reported():
    quote = RecipeCostingModule.quote_all(
        [_recipe(("a", "10", "0"), ("b", "10", "0"))],
        [
            CostingOffer(
                "a1", "a", "s", Decimal("100"), 100,
                valid_from="2026-08-13", valid_to="2026-08-19",
            ),
            CostingOffer(
                "b1", "b", "s", Decimal("100"), 100,
                valid_from="2026-08-12", valid_to="2026-08-20",
            ),
        ],
    )[0]

    assert (quote.valid_from, quote.valid_to) == ("2026-08-13", "2026-08-19")
    assert quote.validity_reason is None


def test_the_same_offers_in_any_order_give_the_same_quote():
    """Deux formats au même prix unitaire ne doivent pas départager par hasard."""
    offers = [
        CostingOffer("A-un-kilo", "riz", "superc_640", Decimal("1000"), 500),
        CostingOffer("B-deux-kilos", "riz", "superc_640", Decimal("2000"), 1000),
    ]
    recipe = _recipe(("riz", "300", "0"))

    forward = RecipeCostingModule.quote_all([recipe], offers)[0]
    backward = RecipeCostingModule.quote_all([recipe], list(reversed(offers)))[0]

    assert forward.as_dict() == backward.as_dict()
    assert forward.ingredients[0].product_external_key == "A-un-kilo"


def test_savings_compare_to_the_basket_you_would_really_buy_without_the_promo():
    """La référence était le prix régulier du panier promotionnel lui-même.

    Quand la promo rend le gros format le moins cher, on le comparait à son
    propre prix régulier — jamais au format qu'on aurait réellement pris. Le
    devis annonçait 17,00 $ d'économie là où l'alternative réelle coûte 4,00 $.
    """
    quote = RecipeCostingModule.quote_all(
        [_recipe(("tomate", "700", "0"))],
        [
            CostingOffer(
                "gros", "tomate", "s", Decimal("800"), 300,
                regular_price_cents_cad=2000, is_promo=True,
            ),
            CostingOffer("petit", "tomate", "s", Decimal("800"), 400),
        ],
    )[0]

    assert quote.autonomous_checkout_cents == Decimal("300.00")
    assert quote.regular_comparable_cents == Decimal("400.00")
    assert quote.promotional_savings_cents == Decimal("100.00")


def test_savings_are_never_negative():
    """Un prix régulier inférieur au prix courant est une donnée fautive."""
    quote = RecipeCostingModule.quote_all(
        [_recipe(("tomate", "100", "0"))],
        [
            CostingOffer(
                "incoherent", "tomate", "s", Decimal("800"), 500,
                regular_price_cents_cad=100, is_promo=True,
            )
        ],
    )[0]

    assert quote.promotional_savings_cents == Decimal("0.00")


def test_a_zero_price_offer_is_never_evidence_of_a_free_ingredient():
    """L'ADR: « une donnée absente ne devient jamais un coût nul ».

    Le filtre acceptait `price_cents_cad >= 0`, donc une offre à zéro remportait
    toujours la sélection au meilleur prix unitaire et rendait la recette
    gratuite avec la confiance `exact`. Le garde-fou n'existait que dans
    l'adaptateur de capture, pas dans le module qui déclare l'invariant.
    """
    quote = RecipeCostingModule.quote_all(
        [_recipe(("riz", "100", "0"))],
        [
            CostingOffer("riz-gratuit", "riz", "superc_640", Decimal("1000"), 0),
            CostingOffer("riz-vrai", "riz", "superc_640", Decimal("1000"), 500),
        ],
    )[0]

    assert quote.consumed_cost_cents == Decimal("50.00")
    assert quote.ingredients[0].product_external_key == "riz-vrai"


def test_only_zero_priced_offers_leave_the_ingredient_incomplete():
    quote = RecipeCostingModule.quote_all(
        [_recipe(("riz", "100", "0"))],
        [CostingOffer("riz-gratuit", "riz", "superc_640", Decimal("1000"), 0)],
    )[0]

    assert quote.status == "incomplete"
    assert quote.consumed_cost_cents is None
    assert quote.ingredients[0].reason == "no_priced_product"


def test_an_ingredient_needed_in_zero_quantity_blocks_nothing():
    """Besoin nul: rien à chiffrer, donc rien à bloquer ni à acheter."""
    quote = RecipeCostingModule.quote_all(
        [_recipe(("garniture", "0", "0"), ("riz", "100", "0"))],
        [CostingOffer("riz", "riz", "superc_640", Decimal("1000"), 500)],
    )[0]

    assert quote.status == "complete"
    assert quote.consumed_cost_cents == Decimal("50.00")
    assert [line.procurement_ingredient_id for line in quote.purchases] == ["riz"]


def test_a_household_staple_is_valued_but_not_bought_again():
    """1,25 g de sel n'achète pas un sac de 1 kg — 800 fois le besoin.

    Le ménage déclare ses essentiels, mais le module de prix ne les lisait pas :
    une trempette d'une portion sortait à 7,80 $ consommés contre 41,81 $ à
    décaisser, dont onze condiments de garde-manger.
    """
    quote = RecipeCostingModule.quote_all(
        [_recipe(("sel_table", "1.25", "0"), ("riz", "500", "0"))],
        [
            CostingOffer("sel-1kg", "sel_table", "s", Decimal("1000"), 199),
            CostingOffer("riz-1kg", "riz", "s", Decimal("1000"), 500),
        ],
        staples=["sel_table"],
    )[0]

    # Le sel est consommé, donc valorisé: il ne devient pas gratuit.
    assert quote.consumed_cost_cents == Decimal("250.25")
    # Mais il n'est pas racheté: seul le riz est au panier.
    assert [line.procurement_ingredient_id for line in quote.purchases] == ["riz"]
    assert quote.autonomous_checkout_cents == Decimal("500.00")
    assert quote.ingredients[0].reason == "household_staple"


def test_a_staple_without_any_priced_product_still_blocks_the_quote():
    """Le mécanisme ne rend pas l'ingrédient invisible, seulement non racheté."""
    quote = RecipeCostingModule.quote_all(
        [_recipe(("epice_rare", "5", "0"))], [], staples=["epice_rare"]
    )[0]

    assert quote.status == "incomplete"
    assert quote.incomplete_ingredients == ("epice_rare",)


def test_explicit_essential_can_be_zero_cost():
    quote = RecipeCostingModule.quote_all(
        [_recipe(("eau", "250", "0"))],
        [],
        supply_rules=[SupplyRule("eau", "essential", confidence="exact")],
    )[0]

    assert quote.status == "complete"
    assert quote.consumed_cost_cents == Decimal("0.00")
    assert quote.autonomous_checkout_cents == Decimal("0.00")
