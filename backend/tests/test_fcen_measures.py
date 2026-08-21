"""La masse d'une unité et la densité se dérivent du FCÉN, ou se refusent.

Les mesures de ce fichier sont celles de l'archive 2026, recopiées telles
quelles. Le refus qui compte est celui de la **densité de tassement** : 250 ml
de mozzarella râpée pèsent 113 g, ce qui donne 0,45 g/ml — un chiffre qui
décrit un contenant, pas un aliment.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.fcen_measures import (
    AMBIGUOUS_COUNT_MEASURES,
    INCONSISTENT_RATIOS,
    NOT_POURABLE,
    NO_COUNT_MEASURE,
    NO_VOLUME_MEASURE,
    OUT_OF_LIQUID_RANGE,
    MeasureWeight,
    propose_density,
    propose_unit_mass,
)


def measure(description, grams, code="1", type_code="6", food="2394"):
    return MeasureWeight(
        food_code=food,
        measure_type_code=type_code,
        measure_code=code,
        description=description,
        grams=Decimal(grams),
    )


def test_the_mass_of_one_clove_of_garlic_comes_from_the_federal_file():
    """Le goulot le plus fréquent du corpus : 68 recettes tiennent à ce chiffre."""
    proposal = propose_unit_mass(
        "gousse_ail",
        "Gousse d'ail",
        "2394",
        "Ail, cru",
        [
            measure("1 gousse", "3"),
            measure("100 ml", "57.481", code="2"),
            measure("1 bulbe", "24", code="3"),
            measure("4 g", "4", code="4"),
        ],
    )
    assert proposal.grams_per_unit == Decimal("3")
    assert proposal.measure_description == "1 gousse"
    assert "2394" in proposal.provenance and "gousse" in proposal.provenance
    assert proposal.reason is None


def test_the_ingredient_name_picks_the_unit_when_the_federal_file_offers_two():
    """« Ail, cru » publie « 1 gousse » (3 g) et « 1 bulbe » (24 g).

    Rien dans le fichier fédéral ne dit laquelle est l'unité de la recette; le
    nom canonique le dit. Un facteur huit se jouait autrement sur la longueur
    d'une étiquette.
    """
    measures = [measure("1 bulbe", "24"), measure("1 gousse", "3", code="2")]
    assert propose_unit_mass(
        "gousse_ail", "Gousse d'ail", "2394", "Ail, cru", measures
    ).grams_per_unit == Decimal("3")
    assert propose_unit_mass(
        "bulbe_ail", "Bulbe d'ail", "2394", "Ail, cru", measures
    ).grams_per_unit == Decimal("24")


def test_egg_calibres_are_refused_rather_than_guessed():
    """L'aliment 125 publie sept calibres d'œuf; le canon en nomme un seul.

    Trouvé en revue, sur les mesures réelles : départager au plus court libellé
    proposait « 1 œuf jumbo » (66,06 g) pour « Œuf de calibre gros » (52,61 g),
    soit 26 % de trop sur le deuxième ingrédient le plus bloquant du corpus. Le
    calibre est un jugement humain, pas une dérivation.
    """
    proposal = propose_unit_mass(
        "oeuf",
        "Œuf de calibre gros",
        "125",
        "Oeuf, poule, entier, frais ou congelé, cru",
        [
            measure("1 oeufs large (gros)", "52.61"),
            measure("1 oeuf extra gros", "58.09", code="2"),
            measure("1 œuf jumbo", "66.06", code="3"),
            measure("1 oeuf moyen", "45.62", code="4"),
            measure("250 ml", "256.762", code="5"),
        ],
    )
    assert proposal.grams_per_unit is None
    assert proposal.reason == AMBIGUOUS_COUNT_MEASURES
    # Le refus publie les candidats : c'est ce qu'un curateur doit lire.
    assert "52.61" in proposal.provenance and "66.06" in proposal.provenance


def test_the_oe_ligature_does_not_split_a_measure_from_its_ingredient():
    """« 1 œuf jumbo » et « 1 oeuf moyen » parlent du même aliment.

    Sans réduction de la ligature, seul le libellé accentué répondait au canon
    « Œuf … », et le jumbo passait pour la seule mesure pertinente.
    """
    proposal = propose_unit_mass(
        "oeuf", "Œuf de calibre gros", "125", "Oeuf, poule",
        [measure("1 œuf jumbo", "66.06"), measure("1 oeuf moyen", "45.62", code="2")],
    )
    assert proposal.reason == AMBIGUOUS_COUNT_MEASURES


def test_a_single_named_measure_is_still_derived():
    """Le refus ne doit pas emporter le cas qui marche : l'ail garde ses 3 g."""
    proposal = propose_unit_mass(
        "gousse_ail", "Gousse d'ail", "2394", "Ail, cru",
        [
            measure("1 gousse", "3"),
            measure("1 bulbe", "24", code="2"),
            measure("100 ml", "57.481", code="3"),
        ],
    )
    assert proposal.grams_per_unit == Decimal("3")
    assert proposal.reason is None


def test_a_count_measure_beyond_one_unit_is_divided_not_copied():
    proposal = propose_unit_mass(
        "coriandre_fraiche", "Coriandre fraîche", "2067", "Coriandre (cilantro), crue",
        [measure("9 branches", "20")],
    )
    # 20 g pour 9 branches, soit 2,222 g l'unité — la division est publiée.
    assert proposal.grams_per_unit == Decimal("2.222")


def test_a_food_measured_only_by_volume_yields_no_unit_mass():
    proposal = propose_unit_mass(
        "lait_325", "Lait 3,25 %", "61", "Lait, 3,25 % M.G.",
        [measure("250 ml", "257.5"), measure("15 ml", "15.45", code="2")],
    )
    assert proposal.grams_per_unit is None
    assert proposal.reason == NO_COUNT_MEASURE


def test_a_gram_label_is_not_a_count():
    """« 0.5g » est une masse déguisée en libellé, pas une unité de service."""
    proposal = propose_unit_mass(
        "feuille_laurier", "Feuille de laurier", "172", "Épices, laurier, feuilles",
        [measure("0.5g", "0.5"), measure("5 ml émietté", "0.612", code="2")],
    )
    assert proposal.grams_per_unit is None
    assert proposal.reason == NO_COUNT_MEASURE


def test_non_serving_measures_are_ignored():
    """Le type 3 décrit une portion non comestible, le type 9 un rendement."""
    proposal = propose_unit_mass(
        "avocat", "Avocat", "1511", "Avocat, cru",
        [
            measure("1 fruit", "201", type_code="3"),
            measure("1 fruit", "201", code="2", type_code="9"),
        ],
    )
    assert proposal.grams_per_unit is None


def test_the_density_of_lemon_juice_comes_from_the_largest_published_volume():
    proposal = propose_density(
        "jus_citron", "1589", "Citron, jus, frais",
        [
            measure("5 ml", "5.156"),
            measure("100 ml", "103.128", code="2"),
            measure("250 ml", "257.819", code="3"),
        ],
    )
    assert proposal.density_g_per_ml == Decimal("1.031")
    assert proposal.reason is None
    assert "1589" in proposal.provenance


def test_grated_cheese_is_refused_because_that_ratio_is_packing():
    """250 ml de mozzarella râpée pèsent 113 g : 0,45 g/ml n'est pas une densité.

    Appliqué à 200 ml de lait, ce rapport rendrait 90 g au lieu de 206.
    """
    proposal = propose_density(
        "mozzarella", "77", "Fromage mozzarella, partiellement écrémé",
        [
            measure("250 ml râpé", "113"),
            measure("125 ml râpé", "56.5", code="2"),
        ],
    )
    assert proposal.density_g_per_ml is None
    assert proposal.reason == NOT_POURABLE
    assert "râpé" in proposal.provenance
    assert proposal.examined


def test_a_pourable_ratio_outside_the_liquid_band_is_refused():
    proposal = propose_density(
        "farine_tout_usage", "4484", "Farine de blé, tout usage",
        [measure("250 ml", "125")],
    )
    assert proposal.density_g_per_ml is None
    assert proposal.reason == OUT_OF_LIQUID_RANGE


def test_ratios_that_disagree_between_volumes_are_refused():
    """Deux volumes du même aliment doivent donner la même densité."""
    proposal = propose_density(
        "epinard_frais", "2626", "Épinard, cru",
        [measure("250 ml", "30"), measure("100 ml", "50", code="2")],
    )
    assert proposal.density_g_per_ml is None
    assert proposal.reason == INCONSISTENT_RATIOS


def test_a_food_without_any_volume_measure_yields_no_density():
    proposal = propose_density(
        "gousse_ail", "2394", "Ail, cru", [measure("1 gousse", "3")]
    )
    assert proposal.density_g_per_ml is None
    assert proposal.reason == NO_VOLUME_MEASURE


def test_the_broth_density_is_the_one_the_negligible_rule_already_cites():
    """Cohérence avec le règlement : 100 ml de bouillon prêt-à-servir = 110 g."""
    proposal = propose_density(
        "bouillon_poulet", "6541", "Soupe, bouillon, poulet, prête-à-servir",
        [
            measure("100 ml", "110.063"),
            measure("125 ml", "138.829", code="2"),
            measure("250 ml", "277.658", code="3"),
        ],
    )
    assert proposal.density_g_per_ml == Decimal("1.111")


def test_a_whipped_measure_sets_itself_aside_instead_of_refusing_the_cream():
    """La crème 35 % est versable; le fichier publie aussi son volume fouetté.

    Refuser l'aliment parce qu'une de ses mesures décrit un état aéré, c'est
    laisser une mesure de tassement disqualifier trois mesures d'écoulement qui
    s'accordent à 1,006 g/ml. Le fromage râpé, lui, n'a que des mesures tassées
    et reste refusé — c'est le test voisin qui le dit.
    """
    proposal = propose_density(
        "creme_35", "138", "Crème à fouetter, 35% M.G.",
        [
            measure("100 ml", "100.592", food="138"),
            measure("100 ml fouetté", "50.719", code="2", food="138"),
            measure("15 ml", "15.088", code="3", food="138"),
            measure("250 ml fouetté", "126.796", code="4", food="138"),
            measure("250 ml liquide (donne 2 tasses fouettée)", "251.479",
                    code="5", food="138"),
        ],
    )
    assert proposal.reason is None
    assert proposal.density_g_per_ml == Decimal("1.006")
    # La mesure retenue est le plus grand volume VERSABLE — celui qui porte le
    # moins d'arrondi fédéral — et les mesures écartées sont nommées. Les deux
    # assertions sont séparées exprès : « 250 ml liquide » figurait aussi dans
    # une provenance qui l'avait écartée, et un test qui cherchait seulement la
    # chaîne passait alors que la mesure retenue était le 100 ml.
    retenue, _, ecartees = proposal.provenance.partition(
        " Mesures tassées ou aérées écartées : "
    )
    assert "250 ml liquide (donne 2 tasses fouettée) = 251.479 g" in retenue
    assert ecartees == "100 ml fouetté, 250 ml fouetté."
    assert len(proposal.examined) == 5
