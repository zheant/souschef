"""Une page de recette devient un brouillon, ou refuse en disant pourquoi.

Les lignes de ce test sont copiées d'une page réelle (bonpourtoi.ca, gabarit
dans `tests/fixtures/`), pas inventées : c'est la forme que les pages publient
vraiment, avec ses parenthèses imbriquées, ses fractions typographiques et son
« Au goût » sans quantité.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.services.recipe_web_extraction import (
    NO_QUANTITY,
    NO_STRUCTURED_RECIPE,
    ExtractionRefused,
    dimension_of,
    extract_recipe,
    parse_ingredient_line,
    resolve_canonical,
)

FIXTURE = (
    Path(__file__).parent / "fixtures" / "bonpourtoi_ailes_de_poulet_buffalo.html"
)


def test_a_page_with_json_ld_becomes_a_draft():
    draft = extract_recipe(FIXTURE.read_bytes(), "https://bonpourtoi.ca/x")
    assert draft.name == "Ailes de poulet Buffalo"
    assert draft.servings == 24
    assert draft.prep_time_h == Decimal("0.25")   # PT15M
    assert draft.cook_time_h == Decimal("0.75")   # PT45M
    assert len(draft.lines) == 13
    assert draft.lines[0].startswith("Sauce piquante au piment")


def test_a_page_without_a_recipe_node_is_refused_by_name():
    """Ricardo publie un noeud « WebSite » et rien d'autre : c'est ce cas."""
    html = b'<html><script type="application/ld+json">{"@type":"WebSite"}</script></html>'
    with pytest.raises(ExtractionRefused) as error:
        extract_recipe(html, "https://exemple.test/x")
    assert error.value.reason == NO_STRUCTURED_RECIPE


@pytest.mark.parametrize(
    "line, quantity, unit, label",
    [
        # La quantité métrique entre parenthèses gagne : c'est celle que la page
        # publie sans ambiguïté d'ustensile.
        ("Sauce piquante au piment (style Red Hot),  ½ tasse (125  ml)",
         Decimal("125"), "millilitre", "sauce piquante au piment (style red hot)"),
        # Parenthèses imbriquées : le millilitre d'abord, le gramme ensuite.
        ("Beurre non salé, 2  c. à soupe (30 ml (30 g)  )",
         Decimal("30"), "millilitre", "beurre non salé"),
        ("Fécule de maïs, 3  c. à soupe (45 ml (25 g)  )",
         Decimal("45"), "millilitre", "fécule de maïs"),
        # Un compte d'articles reste un compte : « 12 ailes » n'est pas 12 g.
        ("Ailes de poulet entières crues, 12 ailes   (12 ailes  )",
         Decimal("12"), "piece", "ailes de poulet entières crues"),
        # Fraction typographique et virgule décimale française.
        ("Paprika fumé,  ½ c. à thé (2,5  ml)",
         Decimal("2.5"), "millilitre", "paprika fumé"),
    ],
)
def test_a_real_line_yields_its_quantity_its_unit_and_its_label(
    line, quantity, unit, label
):
    parsed = parse_ingredient_line(line)
    assert parsed.quantity == quantity
    assert parsed.unit == unit
    assert parsed.label == label


def test_a_line_without_a_quantity_says_so_instead_of_guessing():
    """« Au goût » n'est pas une quantité, et zéro n'en est pas une non plus."""
    parsed = parse_ingredient_line("Sauce au fromage bleu,   Au goût (  Au goût)")
    assert parsed.quantity is None
    assert parsed.reason == NO_QUANTITY
    assert parsed.label == "sauce au fromage bleu"


def test_the_label_resolves_to_a_canonical_ingredient_by_alias():
    aliases = {
        "beurre non salé": "beurre_non_sale",
        "beurre": "beurre_non_precise",
        "paprika fumé": "paprika_fume",
    }
    # Correspondance exacte d'abord.
    assert resolve_canonical("beurre non salé", aliases) == "beurre_non_sale"
    # À défaut, l'alias le plus long contenu dans le libellé : « beurre » plutôt
    # que rien, et jamais un alias plus court quand un plus long correspond.
    assert resolve_canonical("beurre fondu tiède", aliases) == "beurre_non_precise"
    assert resolve_canonical("chocolat noir 70 %", aliases) is None


def test_a_decimal_comma_in_the_label_does_not_cut_it_in_two():
    """« Lait 3,25 %, 750 ml (750 g) » nomme le lait 3,25 %, pas « lait 3 ».

    Couper au premier point-virgule venu donnait le libellé « lait 3 », qui se
    résolvait en « lait non précisé » — un ingrédient voisin mais pas le bon, et
    la valeur nutritive d'un lait entier n'est pas celle d'un lait « non
    précisé ». La coupe se fait donc à la dernière virgule que suit une
    quantité.
    """
    parsed = parse_ingredient_line("Lait 3,25 %, 750 ml (750 g)")
    assert parsed.label == "lait 3,25 %"
    assert parsed.quantity == Decimal("750")
    assert parsed.unit == "millilitre"


@pytest.mark.parametrize(
    "label, expected",
    [
        # Le canon écrit au singulier, la page au pluriel — deux vraies lignes
        # de bonpourtoi.ca.
        ("clous de girofle entiers", "clou_girofle"),
        ("oignons jaunes", "oignon_jaune"),
        # Et l'inverse ne casse pas : un libellé au singulier trouve un alias
        # au pluriel.
        ("tomate cerise", "tomate_cerise"),
    ],
)
def test_a_plural_still_names_its_ingredient(label, expected):
    aliases = {
        "clou de girofle": "clou_girofle",
        "oignon jaune": "oignon_jaune",
        "tomates cerises": "tomate_cerise",
    }
    assert resolve_canonical(label, aliases) == expected


def test_a_longer_alias_still_wins_over_a_shorter_one_after_singularising():
    """Le pluriel ne doit pas faire perdre la précision du canon."""
    aliases = {"oignon": "oignon", "oignon jaune": "oignon_jaune"}
    assert resolve_canonical("oignons jaunes hachés", aliases) == "oignon_jaune"


@pytest.mark.parametrize(
    "unit, dimension",
    [
        ("millilitre", "volume"), ("litre", "volume"), ("cup", "volume"),
        ("tablespoon", "volume"), ("teaspoon", "volume"),
        ("gram", "mass"), ("kilogram", "mass"), ("pound", "mass"),
        ("clove", "count"), ("can", "count"), ("piece", "count"),
        (None, None), ("chose", None),
    ],
)
def test_each_unit_declares_its_dimension(unit, dimension):
    """La dimension sert à refuser une ligne incohérente avec le canon.

    « Ail haché, 1 ½ c. à soupe (22,5 ml) » se résout vers « Gousse d'ail », qui
    se compte à l'unité : 22,5 ml de gousses n'a pas de sens sans équivalence
    curée. L'appelant compare donc la dimension de la ligne à l'unité de base de
    l'ingrédient, et met la ligne en revue plutôt que d'inventer la conversion.
    """
    assert dimension_of(unit) == dimension


def test_a_line_keeps_every_measurement_it_publishes():
    """« 2 c. à soupe (30 ml (30 g)) » publie un volume ET une masse.

    Choisir le millilitre avant de savoir en quoi l'ingrédient se mesure forçait
    ensuite une conversion — donc une densité curée — alors que la page donnait
    le gramme. L'appelant, qui connaît l'unité de base du canon, choisit la
    mesure de la bonne dimension et n'invente rien.
    """
    parsed = parse_ingredient_line("Beurre non salé, 2  c. à soupe (30 ml (30 g)  )")
    assert (Decimal("30"), "millilitre") in parsed.candidates
    assert (Decimal("30"), "gram") in parsed.candidates
    # Le défaut reste la mesure métrique de volume, comme avant.
    assert (parsed.quantity, parsed.unit) == (Decimal("30"), "millilitre")


def test_the_utensil_measure_is_kept_but_never_preferred():
    """« ½ c. à thé (2,5 ml) » publie les deux : la cuillère et le millilitre.

    Les deux sont conservés — une cuillère reste ce que la recette dit — mais le
    millilitre passe devant : il ne dépend pas de la taille d'une cuillère.
    """
    parsed = parse_ingredient_line("Paprika fumé,  ½ c. à thé (2,5  ml)")
    assert (Decimal("2.5"), "millilitre") in parsed.candidates
    assert (Decimal("0.5"), "teaspoon") in parsed.candidates
    assert (parsed.quantity, parsed.unit) == (Decimal("2.5"), "millilitre")
    assert parsed.candidates[0] == (Decimal("2.5"), "millilitre")
