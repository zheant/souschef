from app.adapters.maxi_capture import CanonicalEntry, IdentityRules


def _canonical(ingredient_id, name, *aliases):
    return CanonicalEntry(
        id=ingredient_id,
        name=name,
        unit_kind="mass",
        base_unit="g",
        alias_tokens=tuple(tuple(alias.split()) for alias in aliases),
    )


RULES = IdentityRules(
    composed_markers=("bagel", "craquelin", "pain", "sauce bbq"),
    ingredient_markers={"cheddar": ("sans gras",)},
    wholesale_markers=("caisse", "demi caisse", "cageot"),
    restricted_categories=(
        (
            "/bieres-et-vins",
            frozenset({"vin_rouge_sec", "vin_blanc_sec", "biere_blonde", "cidre_pomme"}),
            "rayon_alcool_ingredient_non_alcoolise",
        ),
    ),
)


def test_a_bagel_is_not_sesame_seeds():
    assert (
        RULES.composed_marker(
            "Bagels aux graines de sésame", _canonical("graines_sesame", "Graines de sésame")
        )
        == "bagel"
    )


def test_a_bread_is_still_a_bread():
    """Le marqueur ne disqualifie que s'il est absent de l'identité visée."""
    assert (
        RULES.composed_marker("Pain au levain frais", _canonical("pain_levain", "Pain au levain"))
        is None
    )


def test_an_alias_defends_the_product():
    """« Sauce BBQ » reste une sauce barbecue si l'alias le dit."""
    canonical = _canonical("sauce_barbecue", "Sauce barbecue", "sauce bbq")
    assert RULES.composed_marker("Sauce BBQ fumée à l'hickory", canonical) is None


def test_matching_is_by_whole_word_not_substring():
    """« Gaufrettes » n'est pas « gaufre », « Pêche beignet » n'est pas un beignet."""
    rules = IdentityRules(composed_markers=("gaufre",))
    assert rules.composed_marker("Gaufrettes à la crème", _canonical("creme", "Crème")) is None


def test_a_marker_can_be_fatal_for_one_ingredient_only():
    """Un bouillon « sans gras » reste un bouillon; un cheddar, non."""
    assert (
        RULES.composed_marker(
            "Bouillon de poulet sans gras", _canonical("bouillon_poulet", "Bouillon de poulet")
        )
        is None
    )
    assert (
        RULES.composed_marker(
            "Fromage cheddar tranché sans gras", _canonical("cheddar", "Cheddar")
        )
        == "sans gras"
    )


def test_a_beer_flavoured_with_honey_is_not_honey():
    """Le cas réel: une bière au miel gagnait la composition du panier du miel.

    Elle perdait la valorisation au prix unitaire, donc elle n'apparaissait que
    dans la liste d'épicerie — c'est pour ça qu'elle avait survécu à la revue
    précédente, qui lisait surtout les coûts consommés.
    """
    assert (
        RULES.restricted_category(
            "/allees/bieres-et-vins/bieres-et-cidre", _canonical("miel", "Miel")
        )
        == "rayon_alcool_ingredient_non_alcoolise"
    )


def test_an_alcoholic_ingredient_is_still_buyable_from_that_aisle():
    """La règle réserve le rayon, elle ne l'interdit pas."""
    for ingredient_id in ("biere_blonde", "vin_rouge_sec", "vin_blanc_sec", "cidre_pomme"):
        assert (
            RULES.restricted_category(
                "/allees/bieres-et-vins/bieres-et-cidre", _canonical(ingredient_id, ingredient_id)
            )
            is None
        )


def test_the_aisle_is_the_evidence_not_a_word_in_the_title():
    """Trois produits qu'un marqueur « biere »/« vin » sur le titre rejetait à tort.

    Ils vivent tous hors du rayon des alcools; le rayon les défend, le titre non.
    """
    cases = [
        ("/allees/garde-manger/condiments-et-garnitures", "sauce_barbecue"),
        ("/allees/produits-surgeles/poissons-et-fruits-de-mer", "aiglefin"),
        ("/allees/garde-manger/huiles-et-vinaigres", "vinaigre_blanc"),
    ]
    for category_url, ingredient_id in cases:
        assert (
            RULES.restricted_category(category_url, _canonical(ingredient_id, ingredient_id))
            is None
        )


def test_an_unrestricted_aisle_never_blocks():
    assert RULES.restricted_category(None, _canonical("miel", "Miel")) is None
    assert (
        RULES.restricted_category("/allees/fruits-et-legumes", _canonical("miel", "Miel"))
        is None
    )


def test_a_wholesale_format_publishes_no_usable_quantity():
    """« Demi caisse de figues fraîches » n'est pas une figue de 50 g.

    Le produit EST bien des figues : ce n'est pas un problème d'identité mais de
    quantité. L'équivalence « 1 figue moyenne = 50 g » avait été appliquée au
    titre d'un format de gros, ce qui valorisait la figue à 200 $/kg.
    """
    assert RULES.wholesale_marker("Demi caisse de figues fraîches") == "demi caisse"
    assert RULES.wholesale_marker("Cageot de tomates") == "cageot"


def test_a_wholesale_marker_matches_whole_words_only():
    """« Casserole » n'est pas une « caisse »."""
    assert RULES.wholesale_marker("Casserole de pommes de terre") is None
    assert RULES.wholesale_marker("Figues fraîches") is None
