"""Décisions durables produit commercial → ingrédient canonique."""

from app.ingestion.retail_product_curation import CanonicalIndex, classify_product


def _index():
    return CanonicalIndex.from_rows(
        [
            {"id": "pomme", "name": "Pomme", "family_id": "fruits"},
            {"id": "poireau", "name": "Poireau", "family_id": "alliums"},
            {"id": "macaroni", "name": "Macaroni", "family_id": "pates"},
            {"id": "pois_vert_surgele", "name": "Pois verts surgelés", "family_id": "legumineuses"},
            {"id": "farine_tout_usage", "name": "Farine tout usage", "family_id": "farines"},
            {"id": "pates_seches", "name": "Pâtes sèches", "family_id": "pates"},
            {"id": "yogourt_nature", "name": "Yogourt nature", "family_id": "produits_laitiers"},
            {"id": "pain_levain", "name": "Pain au levain", "family_id": "pains"},
            {"id": "saucisse_italienne", "name": "Saucisse italienne", "family_id": "viandes"},
        ],
        [
            {"canonical_ingredient_id": "pomme", "alias": "Apple"},
            {"canonical_ingredient_id": "poireau", "alias": "Leek"},
        ],
    )


def _product(name, category, **overrides):
    return {
        "source_product_id": overrides.pop("source_product_id", "1"),
        "name": name,
        "category_url": category,
        "status": overrides.pop("status", "unmatched"),
        "canonical_ingredient_id": overrides.pop("canonical_ingredient_id", None),
        "candidate_ids": overrides.pop("candidate_ids", []),
        **overrides,
    }


def test_fresh_food_is_linked_to_existing_canonical_ingredient():
    decision = classify_product(
        _product(
            "Sac de pommes biologiques",
            "/allees/fruits-et-legumes/fruits/pommes-et-poires",
            status="review",
            candidate_ids=["pomme"],
        ),
        _index(),
    )
    assert decision.action == "link_existing"
    assert decision.canonical_ingredient_id == "pomme"


def test_simple_unmatched_food_uses_a_strong_canonical_name_match():
    decision = classify_product(
        _product(
            "Poireaux",
            "/allees/fruits-et-legumes/legumes/oignons-et-poireaux",
        ),
        _index(),
    )
    assert decision.action == "link_existing"
    assert decision.canonical_ingredient_id == "poireau"


def test_prepared_food_is_excluded_even_when_it_mentions_an_ingredient():
    decision = classify_product(
        _product(
            "Macaroni au fromage",
            "/allees/garde-manger/pates-riz-et-feves/pates",
            status="review",
            candidate_ids=["macaroni"],
        ),
        _index(),
    )
    assert decision.action == "exclude"
    assert decision.reason == "prepared_or_composite_product"


def test_drinks_snacks_and_prepared_frozen_food_are_excluded_by_category():
    categories = (
        "/allees/boissons/boissons-au-soja/boisson-de-soja",
        "/allees/collations/collations-sucrees-et-bonbons/chocolat",
        "/allees/produits-surgeles/repas-et-plats-d-accompagnement/poulet",
    )
    for index, category in enumerate(categories):
        decision = classify_product(
            _product("Produit", category, source_product_id=str(index)),
            _index(),
        )
        assert decision.action == "exclude"


def test_useful_identity_can_be_linked_inside_a_mixed_category():
    for name, category, canonical_id in (
        (
            "Pain au levain",
            "/allees/pains-et-patisseries/pains",
            "pain_levain",
        ),
        (
            "Saucisse italienne",
            "/allees/charcuteries-et-plats-prepares/saucisses",
            "saucisse_italienne",
        ),
    ):
        decision = classify_product(
            _product(name, category, candidate_ids=[canonical_id]), _index()
        )
        assert decision.action == "link_existing"
        assert decision.canonical_ingredient_id == canonical_id


def test_plain_frozen_ingredient_is_not_excluded():
    decision = classify_product(
        _product(
            "Pois verts surgelés",
            "/allees/produits-surgeles/fruits-et-legumes/legumes",
            status="review",
            candidate_ids=["pois_vert_surgele"],
        ),
        _index(),
    )
    assert decision.action == "link_existing"
    assert decision.canonical_ingredient_id == "pois_vert_surgele"


def test_simple_food_without_sufficient_evidence_becomes_a_canonical_gap():
    decision = classify_product(
        _product(
            "Fruit mystérieux",
            "/allees/fruits-et-legumes/fruits/avocats-et-fruits-exotiques",
        ),
        _index(),
    )
    assert decision.action == "canonical_gap"
    assert decision.canonical_ingredient_id is None


def test_plain_pasta_shape_maps_to_generic_dry_pasta():
    decision = classify_product(
        _product("Pâtes farfalle", "/allees/garde-manger/pates-riz-et-feves/pates"),
        _index(),
    )
    assert decision.action == "link_existing"
    assert decision.canonical_ingredient_id == "pates_seches"


def test_flavoured_yogurt_is_excluded_but_plain_yogurt_is_linked():
    category = "/allees/produits-laitiers-et-oeufs/yogourts/yogourts-en-pot"
    flavoured = classify_product(_product("Yogourt aux fraises", category), _index())
    plain = classify_product(_product("Yogourt probiotique nature", category), _index())
    assert flavoured.action == "exclude"
    assert plain.canonical_ingredient_id == "yogourt_nature"
