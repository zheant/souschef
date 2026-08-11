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
