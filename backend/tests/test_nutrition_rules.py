"""Le règlement « apport négligeable » est déclaré, borné, et refuse le reste.

Un apport déclaré négligeable sans borne mesurée n'est pas une règle, c'est une
omission qui s'ignore elle-même. Ces tests exercent les deux refus qui font la
différence : une entrée dont la borne n'a jamais été mesurée, et une quantité
au-delà de celle sur laquelle la borne a été mesurée.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.nutrition_rules import (
    BASE_UNIT_MISMATCH,
    NEGLIGIBLE,
    NOT_DECLARED,
    OVER_DECLARED_QUANTITY,
    NutritionRulesInvalid,
    parse_nutrition_rules,
)

CONFIG = Path(__file__).resolve().parents[2] / "config" / "nutrition-rules.json"


def _payload(**overrides) -> dict:
    entry = {
        "ingredient_id": "sel_table",
        "base_unit": "g",
        "kcal_per_100g": "0",
        "protein_g_per_100g": "0",
        "fat_g_per_100g": "0",
        "carbohydrate_g_per_100g": "0",
        "max_qty_per_serving_base_unit": "15",
        "grams_per_base_unit_ceiling": "1",
        "basis": "Le sel ne porte aucune énergie.",
        "provenance": "FCÉN 2026, aliment 214 « Sel, table » : 0 kcal/100 g.",
    }
    entry.update(overrides)
    return {
        "rule_version": "test",
        "source_version": "2026",
        "negligible_contributions": [entry],
    }


def test_a_declared_ingredient_within_its_ceiling_is_negligible():
    rules = parse_nutrition_rules(_payload())
    verdict = rules.negligible_verdict(
        ingredient_id="sel_table", family_id="epices",
        base_unit="g", qty_per_serving=Decimal("3"),
    )
    assert verdict.kind == NEGLIGIBLE
    assert verdict.kcal_bound == Decimal("0")


def test_an_undeclared_ingredient_is_not_negligible():
    rules = parse_nutrition_rules(_payload())
    verdict = rules.negligible_verdict(
        ingredient_id="beurre", family_id="produits_laitiers",
        base_unit="g", qty_per_serving=Decimal("10"),
    )
    assert verdict.kind == NOT_DECLARED
    assert verdict.claim is None


def test_the_bound_is_computed_at_the_quantity_actually_used():
    """La borne suit la quantité de la ligne, pas le plafond de la règle.

    Sinon une pincée de cumin porterait la borne d'une cuillère à soupe, et le
    « ± » affiché à la recette serait faux dans le sens le plus embarrassant :
    trop large, donc inutile.
    """
    rules = parse_nutrition_rules(
        _payload(ingredient_id="cumin_moulu", kcal_per_100g="375",
                 max_qty_per_serving_base_unit="2.5")
    )
    verdict = rules.negligible_verdict(
        ingredient_id="cumin_moulu", family_id="epices",
        base_unit="g", qty_per_serving=Decimal("1"),
    )
    # 375 kcal/100 g × 1 g = 3,75 kcal, arrondi vers le haut au dixième.
    assert verdict.kind == NEGLIGIBLE
    assert verdict.kcal_bound == Decimal("3.8")
    assert verdict.claim.kcal_bound_at_ceiling == Decimal("9.4")


def test_a_quantity_above_the_ceiling_voids_the_claim():
    """375 g de basilic dans une panzanella ne sont pas un assaisonnement."""
    rules = parse_nutrition_rules(
        _payload(ingredient_id="basilic_frais", kcal_per_100g="23",
                 max_qty_per_serving_base_unit="5")
    )
    verdict = rules.negligible_verdict(
        ingredient_id="basilic_frais", family_id="herbes",
        base_unit="g", qty_per_serving=Decimal("187.5"),
    )
    assert verdict.kind == OVER_DECLARED_QUANTITY
    assert verdict.kcal_bound == Decimal("0")
    assert "187.5" in verdict.reason and "5" in verdict.reason


def test_a_family_claim_covers_its_members_and_yields_to_an_ingredient_claim():
    payload = _payload()
    payload["negligible_contributions"].append(
        {
            "family_id": "epices",
            "base_unit": "g",
            "kcal_per_100g": "525",
            "protein_g_per_100g": "26.63",
            "fat_g_per_100g": "41.56",
            "carbohydrate_g_per_100g": "80.59",
            "max_qty_per_serving_base_unit": "2.5",
            "grams_per_base_unit_ceiling": "1",
            "basis": "Pire densité énergétique des épices du corpus.",
            "provenance": "FCÉN 2026, aliment 193 « Épices, muscade, moulue ».",
        }
    )
    rules = parse_nutrition_rules(payload)

    member = rules.negligible_verdict(
        ingredient_id="cumin_moulu", family_id="epices",
        base_unit="g", qty_per_serving=Decimal("1"),
    )
    assert member.kind == NEGLIGIBLE
    assert member.claim.scope == "family"

    # Le sel est une épice au sens du canon, mais il porte sa propre borne :
    # 0 kcal jusqu'à 15 g, là où la famille s'arrête à 2,5 g.
    salt = rules.negligible_verdict(
        ingredient_id="sel_table", family_id="epices",
        base_unit="g", qty_per_serving=Decimal("7.5"),
    )
    assert salt.kind == NEGLIGIBLE
    assert salt.claim.scope == "ingredient"
    assert salt.kcal_bound == Decimal("0")


def test_a_claim_measured_in_grams_does_not_answer_for_millilitres():
    """Une borne mesurée par gramme ne dit rien d'un volume ni d'un compte.

    C'est le piège qui a produit 2 000 g de roquette pour deux portions
    ailleurs dans ce corpus : un millilitre lu comme un gramme. La règle refuse
    d'appliquer une borne hors de l'unité où elle a été mesurée.
    """
    rules = parse_nutrition_rules(
        _payload(ingredient_id="cardamome_graine", kcal_per_100g="312")
    )
    verdict = rules.negligible_verdict(
        ingredient_id="cardamome_graine", family_id="epices",
        base_unit="ml", qty_per_serving=Decimal("1.25"),
    )
    assert verdict.kind == BASE_UNIT_MISMATCH
    assert "ml" in verdict.reason and "g" in verdict.reason


@pytest.mark.parametrize(
    "override, missing",
    [
        ({"kcal_per_100g": None}, "kcal_per_100g"),
        ({"fat_g_per_100g": None}, "fat_g_per_100g"),
        ({"protein_g_per_100g": None}, "protein_g_per_100g"),
        ({"carbohydrate_g_per_100g": None}, "carbohydrate_g_per_100g"),
        ({"max_qty_per_serving_base_unit": None}, "max_qty_per_serving_base_unit"),
        ({"grams_per_base_unit_ceiling": None}, "grams_per_base_unit_ceiling"),
        ({"provenance": ""}, "provenance"),
        ({"basis": ""}, "basis"),
    ],
)
def test_an_entry_whose_bound_was_never_measured_is_refused(override, missing):
    payload = _payload()
    payload["negligible_contributions"][0].update(override)
    with pytest.raises(NutritionRulesInvalid) as error:
        parse_nutrition_rules(payload)
    assert missing in str(error.value)


def test_a_gram_entry_cannot_declare_a_ceiling_other_than_one():
    """Un gramme est un gramme : toute autre valeur est une faute de saisie."""
    with pytest.raises(NutritionRulesInvalid):
        parse_nutrition_rules(_payload(grams_per_base_unit_ceiling="0.5"))


def test_the_same_scope_cannot_be_declared_twice():
    payload = _payload()
    payload["negligible_contributions"].append(
        dict(payload["negligible_contributions"][0])
    )
    with pytest.raises(NutritionRulesInvalid) as error:
        parse_nutrition_rules(payload)
    assert "sel_table" in str(error.value)


def test_an_entry_must_name_exactly_one_scope():
    with pytest.raises(NutritionRulesInvalid):
        parse_nutrition_rules(_payload(family_id="epices"))
    payload = _payload()
    del payload["negligible_contributions"][0]["ingredient_id"]
    with pytest.raises(NutritionRulesInvalid):
        parse_nutrition_rules(payload)


def test_a_food_choice_needs_a_written_rationale_and_a_known_kind():
    base = {
        "ingredient_id": "mais",
        "food_code": "2388",
        "kind": "correction",
        "rationale": "Le canon a été créé depuis des pâtes de maïs.",
        "provenance": "FCÉN 2026, aliment 2388 « Maïs sucré, jaune, cru ».",
    }
    rules = parse_nutrition_rules(
        {"rule_version": "test", "source_version": "2026", "food_choices": [base]}
    )
    assert rules.food_choice("mais").food_code == "2388"
    assert rules.food_choice("avocat") is None

    for override in ({"rationale": ""}, {"kind": "parce_que"}, {"food_code": ""}):
        with pytest.raises(NutritionRulesInvalid):
            parse_nutrition_rules(
                {
                    "rule_version": "test",
                    "source_version": "2026",
                    "food_choices": [{**base, **override}],
                }
            )


def test_a_ruleset_must_name_the_archive_edition_it_was_measured_on():
    """Une borne mesurée sur une édition ne vaut pas pour une autre.

    C'est aussi ce que la façade SQL lit pour ne pas mélanger deux éditions
    chargées dans la même base — l'énergie de l'une et les lipides de l'autre.
    """
    payload = _payload()
    del payload["source_version"]
    with pytest.raises(NutritionRulesInvalid) as error:
        parse_nutrition_rules(payload)
    assert "source_version" in str(error.value)


def test_the_delivered_rules_file_parses_and_every_entry_is_measured():
    """Le fichier livré est lu par le module, la façade et l'audit.

    Le module des prix a déjà répondu 500 dans la pile livrée pour un fichier
    de règles absent du conteneur (D-config/MENU_CONFIG_DIR). Celui-ci est donc
    exercé tel qu'il est versionné, pas seulement en fabriques de test.
    """
    rules = parse_nutrition_rules(
        json.loads(CONFIG.read_text(encoding="utf-8"))
    )
    assert rules.rule_version
    assert rules.source_version == "2026"
    assert rules.negligible, "Le règlement livré ne déclare aucun apport."
    for claim in rules.negligible:
        assert claim.provenance and claim.basis
        bounds = claim.bounds_at_ceiling
        # Les quatre bornes existent, et aucune n'est négative.
        assert min(
            bounds.kcal, bounds.protein_g, bounds.fat_g, bounds.carbohydrate_g
        ) >= 0
    for choice in rules.food_choices:
        assert choice.rationale and choice.provenance


@pytest.mark.parametrize(
    "payload",
    [
        {"negligible_contributions": None},
        {"food_choices": None},
        {"food_choices": ["oops"]},
        {"negligible_contributions": ["oops"]},
    ],
)
def test_a_block_that_is_not_a_list_of_entries_is_refused_by_name(payload):
    """Un règlement à moitié écrit doit refuser, pas exploser.

    `payload.get(clé, [])` ne protège que d'une clé absente : une clé à `null`
    ou une entrée qui n'est pas un objet remontaient en `TypeError` ou
    `AttributeError` depuis le fond de la couche services. La façade ne rattrape
    que `NutritionRulesInvalid`, donc c'était une 500 là où une 503 nommée était
    due.
    """
    with pytest.raises(NutritionRulesInvalid):
        parse_nutrition_rules(
            {"rule_version": "test", "source_version": "2026", **payload}
        )
