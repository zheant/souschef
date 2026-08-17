from app.services.recipe_quality import review_recipe, review_recipes


CANONICAL = [
    {"id": "aubergine", "family_id": "legumes", "base_unit": "g"},
    {"id": "sel_table", "family_id": "epices", "base_unit": "g"},
    {"id": "oeuf", "family_id": "oeufs", "base_unit": "unit"},
    {"id": "huile_olive", "family_id": "huiles", "base_unit": "ml"},
]


def _recipe(recipe_id, servings, *ingredients, tags=None):
    return {
        "id": recipe_id,
        "name": recipe_id,
        "original_servings": servings,
        "tags": tags or {},
        "ingredients": [
            {
                "canonical_ingredient_id": ingredient_id,
                "qty_fixed_per_batch_base_unit": fixed,
                "qty_marginal_per_serving_base_unit": marginal,
            }
            for ingredient_id, fixed, marginal in ingredients
        ],
    }


def test_one_gram_of_a_vegetable_is_reported():
    flags = review_recipe(
        _recipe("parmigiana", 4, ("aubergine", "1", "0")),
        {row["id"]: row for row in CANONICAL},
    )

    assert [flag.kind for flag in flags] == ["implausible_quantity"]
    assert flags[0].subject == "aubergine"
    assert flags[0].detail == "1 g pour 4 portions"


def test_a_pinch_of_salt_is_not_a_defect():
    """Le seuil vise les erreurs de conversion, pas les épices."""
    flags = review_recipe(
        _recipe("omelette", 4, ("sel_table", "1.25", "0"), ("huile_olive", "2", "0")),
        {row["id"]: row for row in CANONICAL},
    )

    assert flags == ()


def test_duplicate_ingredient_is_named():
    flags = review_recipe(
        _recipe("teriyaki", 4, ("oeuf", "0", "1"), ("oeuf", "2", "0")),
        {row["id"]: row for row in CANONICAL},
    )

    assert [flag.kind for flag in flags] == ["duplicate_ingredient"]


def test_a_yield_counted_in_pieces_is_reported():
    flags = review_recipe(
        _recipe(
            "boulettes", 20, ("oeuf", "2", "0"), tags={"servings_source": "20 boulettes", "import_origin": "corpus"}
        ),
        {row["id"]: row for row in CANONICAL},
    )

    assert [flag.kind for flag in flags] == ["yield_not_in_servings"]


def test_a_large_batch_declared_in_servings_is_not_a_defect():
    """Une tourtière à 24 portions est légitime : c'est la preuve qui compte,
    pas le seuil."""
    flags = review_recipe(
        _recipe(
            "tourtieres", 24, ("oeuf", "2", "0"), tags={"servings_source": "24 portion(s)", "import_origin": "corpus"}
        ),
        {row["id"]: row for row in CANONICAL},
    )

    assert flags == ()


def test_a_curated_yield_is_trusted():
    flags = review_recipe(
        _recipe(
            "boulettes",
            5,
            ("oeuf", "2", "0"),
            tags={
                "servings_source": "20 boulettes",
                "servings_basis": "curated_from_recipe_yield_and_instructions",
                "import_origin": "corpus",
            },
        ),
        {row["id"]: row for row in CANONICAL},
    )

    assert flags == ()


def test_a_sound_recipe_is_absent_from_the_report():
    reviewed = review_recipes(
        [
            _recipe("saine", 4, ("aubergine", "600", "0")),
            _recipe("fautive", 4, ("aubergine", "1", "0")),
        ],
        CANONICAL,
    )

    assert list(reviewed) == ["fautive"]


def test_a_yield_in_pieces_is_reported_even_without_a_known_unit():
    """« 2 douzaines » n'a aucun marqueur connu, et passait pour ça.

    La règle listait des unités (« bouchée », « boulette ») et absolvait tout ce
    qui n'y figurait pas. Elle demande désormais une preuve, pas l'absence d'un
    marqueur.
    """
    flags = review_recipe(
        _recipe(
            "boulettes", 2, ("oeuf", "2", "0"),
            tags={"servings_source": "2 douzaines", "import_origin": "corpus"},
        ),
        {row["id"]: row for row in CANONICAL},
    )

    assert [flag.kind for flag in flags] == ["yield_not_in_servings"]


def test_a_bare_number_matching_the_serving_count_is_proof_enough():
    """Le détaillant publie un champ « portions » sans en répéter l'unité."""
    flags = review_recipe(
        _recipe(
            "gratin", 6, ("oeuf", "2", "0"),
            tags={"servings_source": "6", "import_origin": "corpus"},
        ),
        {row["id"]: row for row in CANONICAL},
    )

    assert flags == ()


def test_a_missing_yield_is_no_longer_taken_for_a_sound_one():
    flags = review_recipe(
        _recipe("mystere", 4, ("oeuf", "2", "0"), tags={"import_origin": "corpus"}),
        {row["id"]: row for row in CANONICAL},
    )

    assert [flag.kind for flag in flags] == ["yield_not_in_servings"]


def test_a_hand_written_seed_recipe_needs_no_published_yield():
    """Ses portions sont un choix, pas la lecture d'une source."""
    flags = review_recipe(
        _recipe("chili_lentilles", 4, ("oeuf", "2", "0")),
        {row["id"]: row for row in CANONICAL},
    )

    assert flags == ()


def test_two_kilos_of_arugula_for_two_servings_is_reported():
    """Le cas réel: la recette la plus chère du rapport, sans aucune réserve.

    La règle ne voyait que les quantités trop petites. Un seuil unique en
    grammes ne peut pas trancher — la borne est par famille et par portion.
    """
    flags = review_recipe(
        _recipe("panzanella", 2, ("aubergine", "2000", "0")),
        {row["id"]: row for row in CANONICAL},
    )

    assert [flag.kind for flag in flags] == ["implausible_quantity_per_serving"]
    assert "1000 g par portion" in flags[0].detail


def test_a_generous_but_ordinary_portion_is_not_reported():
    flags = review_recipe(
        _recipe("ratatouille", 4, ("aubergine", "2000", "0")),
        {row["id"]: row for row in CANONICAL},
    )

    assert flags == ()


def test_a_family_without_a_published_norm_is_never_bounded():
    """Mieux vaut ne rien dire que de signaler une quantité juste."""
    canonical = {"exotique": {"id": "exotique", "family_id": "inconnue", "base_unit": "g"}}
    flags = review_recipe(_recipe("plat", 1, ("exotique", "99999", "0")), canonical)

    assert flags == ()
