"""Un choix d'aliment s'écrit avec sa provenance, ou ne s'écrit pas.

Le motif que ces tests ferment a déjà mordu ce chantier : une provenance
rétro-calculée depuis la valeur retenue, au lieu d'être transcrite de
l'archive. Elle se lit comme vérifiable et ne l'est pas. Ici, la provenance
n'est jamais un argument — elle est rendue depuis les teneurs publiées.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.food_choice_ledger import (
    FoodChoiceDecision,
    FoodChoiceRefused,
    merge_food_choices,
    render_food_choices,
)
from app.services.recipe_nutrition import NutrientFacts

FLOUR = NutrientFacts(
    food_code="4484",
    food_name="Grains céréaliers, farine de blé, tout usage, enrichie",
    kcal_per_100g=Decimal("364"),
    protein_g_per_100g=Decimal("10.33"),
    fat_g_per_100g=Decimal("0.98"),
    carbohydrate_g_per_100g=Decimal("76.31"),
    source_version="2026",
)
FOODS = {"4484": FLOUR}

#: Le canon, tel que le script le construit : chaque ingrédient y figure,
#: avec la liste — parfois vide — des aliments que le pont lui rattache.
CANON = {"farine_tout_usage": (), "mais": ()}


def decision(**kwargs):
    base = {
        "ingredient_id": "farine_tout_usage",
        "food_code": "4484",
        "kind": "attachment",
        "rationale": "Le pont d'identité n'a rien rattaché; le FCÉN publie l'aliment.",
    }
    return FoodChoiceDecision(**{**base, **kwargs})


def test_the_provenance_is_rendered_from_the_published_amounts():
    (entry,) = render_food_choices([decision()], FOODS, CANON)
    assert entry["ingredient_id"] == "farine_tout_usage"
    assert entry["food_code"] == "4484"
    assert entry["kind"] == "attachment"
    assert entry["rationale"].startswith("Le pont d'identité")
    # Les quatre teneurs publiées, telles quelles, et le nom fédéral.
    assert "FCÉN 2026, aliment 4484" in entry["provenance"]
    assert "farine de blé, tout usage, enrichie" in entry["provenance"]
    assert "364 kcal" in entry["provenance"]
    assert "10,33 g de protéines" in entry["provenance"]
    assert "0,98 g de lipides" in entry["provenance"]
    assert "76,31 g de glucides" in entry["provenance"]


def test_a_food_the_archive_does_not_publish_is_refused():
    with pytest.raises(FoodChoiceRefused) as error:
        render_food_choices([decision(food_code="99999")], FOODS, CANON)
    assert "99999" in str(error.value)


def test_a_decision_without_a_written_rationale_is_refused():
    with pytest.raises(FoodChoiceRefused):
        render_food_choices([decision(rationale="   ")], FOODS, CANON)


def test_an_attachment_is_refused_when_the_bridge_already_attached_something():
    """Le contrôle que le parseur ne peut pas faire : il ne voit pas le pont.

    Sans lui, « attachment » deviendrait le kind par défaut de 189 entrées, y
    compris là où un rattachement existe et devrait être choisi ou récusé.
    """
    with pytest.raises(FoodChoiceRefused) as error:
        render_food_choices(
            [decision()], FOODS, {"farine_tout_usage": ("4515",)}
        )
    assert "4515" in str(error.value)


def test_a_primary_must_name_one_of_the_attached_foods():
    with pytest.raises(FoodChoiceRefused):
        render_food_choices(
            [decision(kind="primary")],
            FOODS,
            {"farine_tout_usage": ("4515", "4595")},
        )
    (entry,) = render_food_choices(
        [decision(kind="primary")],
        FOODS,
        {"farine_tout_usage": ("4484", "4595")},
    )
    assert entry["kind"] == "primary"


def test_the_same_ingredient_cannot_be_decided_twice_in_one_batch():
    with pytest.raises(FoodChoiceRefused):
        render_food_choices([decision(), decision()], FOODS, CANON)


def test_merging_keeps_the_existing_entries_and_refuses_to_redecide_one():
    existing = [
        {
            "ingredient_id": "mais",
            "food_code": "2388",
            "kind": "correction",
            "rationale": "…",
            "provenance": "…",
        }
    ]
    (entry,) = render_food_choices([decision()], FOODS, CANON)
    merged = merge_food_choices(existing, [entry])
    assert [row["ingredient_id"] for row in merged] == ["farine_tout_usage", "mais"]

    with pytest.raises(FoodChoiceRefused) as error:
        merge_food_choices(existing, [{**entry, "ingredient_id": "mais"}])
    assert "mais" in str(error.value)


def test_a_kind_the_ruleset_does_not_know_is_refused_before_it_reaches_disk():
    """Le règlement écrit ici est relu par parse_nutrition_rules, qui refuse un
    titre inconnu. Sans ce contrôle, une faute de frappe dans les décisions
    rendait le fichier livré illisible pour son propre parseur — donc l'API en
    503 sur toutes les recettes, et l'audit en exception.
    """
    with pytest.raises(FoodChoiceRefused) as error:
        render_food_choices([decision(kind="attachement")], FOODS, CANON)
    assert "attachement" in str(error.value)


def test_an_ingredient_the_canon_does_not_carry_is_refused():
    """« Ne porte aucun aliment » et « n'existe pas » ne sont pas le même cas.

    Une entrée sur un identifiant fautif se lit comme une décision prise,
    passe le parseur, et ne débloque rien : la couverture ne bouge pas et
    personne ne sait pourquoi.
    """
    with pytest.raises(FoodChoiceRefused) as error:
        render_food_choices(
            [decision(ingredient_id="farine_tout_usag")], FOODS, CANON
        )
    assert "farine_tout_usag" in str(error.value)
