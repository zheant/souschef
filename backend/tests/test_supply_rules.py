"""Résolution des règles d'approvisionnement, partagée par les deux lecteurs.

Le calcul de prix ne faisait qu'un seul saut et exigeait un produit commercial
au bout de ce saut, pendant que l'audit de couverture itérait jusqu'au point
fixe. Les deux lisaient le même fichier de règles et ne s'accordaient donc pas
sur l'ensemble des recettes chiffrables. Un seul résolveur supprime la
divergence par construction.
"""

from decimal import Decimal

import pytest

from app.services.supply_rules import (
    CyclicSupplyRuleError,
    SupplyRule,
    resolve_supply,
)


def _index(*rules: SupplyRule) -> dict[str, SupplyRule]:
    return {rule.ingredient_id: rule for rule in rules}


def test_an_ingredient_without_rule_procures_itself():
    resolution = resolve_supply("riz", {})
    assert resolution.kind == "direct"
    assert resolution.procurement_ingredient_id == "riz"
    assert resolution.factor == Decimal("1")
    assert resolution.confidence == "exact"


def test_a_single_derivation_carries_its_factor_and_provenance():
    rules = _index(
        SupplyRule("jus_citron", "derived", "citron", Decimal("0.5"), provenance="conversion")
    )
    resolution = resolve_supply("jus_citron", rules)
    assert resolution.procurement_ingredient_id == "citron"
    assert resolution.factor == Decimal("0.5")
    assert resolution.provenance == "conversion"


def test_a_chain_multiplies_its_factors_and_keeps_the_worst_confidence():
    rules = _index(
        SupplyRule("jus_lime", "derived", "lime_pressee", Decimal("2"), confidence="estimated"),
        SupplyRule(
            "lime_pressee", "derived", "lime", Decimal("3"), confidence="audited_conversion"
        ),
    )
    resolution = resolve_supply("jus_lime", rules)

    assert resolution.procurement_ingredient_id == "lime"
    assert resolution.factor == Decimal("6")
    assert resolution.confidence == "estimated"
    assert resolution.chain == ("jus_lime", "lime_pressee", "lime")


def test_a_chain_that_ends_on_an_essential_is_essential():
    """Un bouillon dérivé de l'eau coûte zéro, il n'est pas « non chiffrable »."""
    rules = _index(
        SupplyRule("bouillon", "derived", "eau", Decimal("1")),
        SupplyRule("eau", "essential", provenance="eau du robinet"),
    )
    resolution = resolve_supply("bouillon", rules)

    assert resolution.kind == "essential"
    assert resolution.procurement_ingredient_id is None


def test_an_incomplete_derived_rule_is_named_not_silently_direct():
    rules = _index(SupplyRule("mystere", "derived", None, None))
    assert resolve_supply("mystere", rules).kind == "invalid_rule"


def test_a_cycle_is_detected_rather_than_looped():
    rules = _index(
        SupplyRule("a", "derived", "b", Decimal("1")),
        SupplyRule("b", "derived", "a", Decimal("1")),
    )
    with pytest.raises(CyclicSupplyRuleError) as error:
        resolve_supply("a", rules)
    assert "a" in str(error.value)


def test_an_unknown_rule_kind_is_refused():
    rules = _index(SupplyRule("truc", "magique"))
    with pytest.raises(ValueError):
        resolve_supply("truc", rules)
