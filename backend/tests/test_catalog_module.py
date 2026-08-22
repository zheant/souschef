"""Tests directs de ``services/catalog.py`` (CatalogModule), contre
PostgreSQL réel — complète ``tests/test_api.py`` (contrat HTTP)."""

from __future__ import annotations

import pytest

from app.services import catalog
from tests.db_fixtures import db_session, test_engine, toy_seeded  # noqa: F401


def test_search_recipes_pagination_and_filters(db_session):
    page = catalog.search_recipes(db_session, catalog.RecipeQuery(limit=2))
    assert page.total == 3 and len(page.items) == 2

    page = catalog.search_recipes(db_session, catalog.RecipeQuery(q="dahl"))
    assert [r.id for r in page.items] == ["dahl_toy"]


def test_list_stores(db_session):
    stores = catalog.list_stores(db_session)
    assert [s.external_key for s in stores] == ["toy_store"]


def test_get_recipe_ingredients(db_session):
    """Détail recette (pilote, docs/product-pilot.md) — ``Recipe.ingredients``
    existait en base depuis l'étape 1 mais n'était exposé par aucune route."""
    lines = catalog.get_recipe_ingredients(db_session, "riz_nature")
    assert [l.canonical_ingredient_id for l in lines] == ["riz"]
    assert lines[0].name == "Riz"


def test_get_recipe_ingredients_unknown_recipe(db_session):
    with pytest.raises(catalog.RecipeNotFound):
        catalog.get_recipe_ingredients(db_session, "inexistante")


def _draft(**overrides):
    draft = {
        "name": "Salade d'essai",
        "original_servings": 4,
        "prep_time_fixed_h": "0.25",
        "prep_time_marginal_h": "0",
        "min_batch_servings": 4,
        "max_batch_servings": 8,
        "ingredients": [
            {
                "canonical_ingredient_id": "riz",
                "qty_fixed_per_batch_base_unit": "300",
                "qty_marginal_per_serving_base_unit": "0",
            }
        ],
    }
    draft.update(overrides)
    return catalog.RecipeDraft(**draft)


def test_a_recipe_created_from_the_app_is_readable_at_once(db_session):
    created = catalog.create_recipe(db_session, _draft())
    assert created.id == "salade_d_essai"
    lines = catalog.get_recipe_ingredients(db_session, created.id)
    assert [l.canonical_ingredient_id for l in lines] == ["riz"]
    # L'origine est inscrite : une recette venue de l'application ne se
    # confond pas avec une recette du seed, qui reviendrait à son rechargement.
    page = catalog.search_recipes(db_session, catalog.RecipeQuery(q="essai"))
    assert page.items[0].tags["import_origin"] == "app"


def test_a_recipe_naming_an_unknown_ingredient_is_refused(db_session):
    with pytest.raises(catalog.RecipeDraftInvalid) as error:
        catalog.create_recipe(
            db_session,
            _draft(ingredients=[
                {
                    "canonical_ingredient_id": "licorne_hachee",
                    "qty_fixed_per_batch_base_unit": "1",
                    "qty_marginal_per_serving_base_unit": "0",
                }
            ]),
        )
    assert "licorne_hachee" in str(error.value)


def test_a_recipe_without_any_quantity_is_refused(db_session):
    """Une recette dont tout est à zéro ne demande rien : le solveur la
    servirait gratuitement (D25)."""
    with pytest.raises(catalog.RecipeDraftInvalid):
        catalog.create_recipe(
            db_session,
            _draft(ingredients=[
                {
                    "canonical_ingredient_id": "riz",
                    "qty_fixed_per_batch_base_unit": "0",
                    "qty_marginal_per_serving_base_unit": "0",
                }
            ]),
        )


def test_two_recipes_of_the_same_name_do_not_collide(db_session):
    first = catalog.create_recipe(db_session, _draft())
    second = catalog.create_recipe(db_session, _draft())
    assert second.id != first.id and second.id.startswith(first.id)


def test_a_recipe_is_deleted_with_its_lines(db_session):
    created = catalog.create_recipe(db_session, _draft())
    catalog.delete_recipe(db_session, created.id)
    with pytest.raises(catalog.RecipeNotFound):
        catalog.get_recipe_ingredients(db_session, created.id)


def test_deleting_an_unknown_recipe_says_so(db_session):
    with pytest.raises(catalog.RecipeNotFound):
        catalog.delete_recipe(db_session, "inexistante")


def test_a_recipe_used_by_a_plan_is_not_deleted_silently(db_session):
    """`_plan_view` fait `recipes[rid]` sans garde : retirer la recette sans le
    plan échangerait un faux menu contre une 500 (même piège que
    `scripts/purge_demo_recipes.py`)."""
    from app.models import Plan

    db_session.add(
        Plan(
            household_profile_id="default",
            status="proposed",
            on_date=__import__("datetime").date(2026, 8, 21),
            solver_status="Optimal",
            config={},
            servings={"riz_nature": 4},
            diagnostic={},
        )
    )
    db_session.flush()
    with pytest.raises(catalog.RecipeInUse) as error:
        catalog.delete_recipe(db_session, "riz_nature")
    assert "riz_nature" in str(error.value)

    # Avec la décision explicite, le plan part avec la recette.
    catalog.delete_recipe(db_session, "riz_nature", drop_plans=True)
    with pytest.raises(catalog.RecipeNotFound):
        catalog.get_recipe_ingredients(db_session, "riz_nature")
