"""Conversion du corpus Cook vers le contrat recette Souschef."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from app.ports.dto import RecipeDTO


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "import_cook_recipes.py"
SPEC = importlib.util.spec_from_file_location("import_cook_recipes", SCRIPT)
recipe_import = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = recipe_import
SPEC.loader.exec_module(recipe_import)


def _source_recipe(*, status="READY", quantity="100", canonical="carotte"):
    return {
        "source": "ricardo",
        "source_url": "https://www.ricardocuisine.com/recettes/1234-potage-test",
        "title": "Potage test",
        "import_status": status,
        "review_flags": [],
        "souschef_projection": {
            "name": "Potage test",
            "original_servings": 4,
            "prep_time_fixed_h": 0.25,
            "prep_time_marginal_h": 0,
            "min_batch_servings": 4,
            "max_batch_servings": 8,
            "tags": {"categories": ["Soupes"]},
            "required_equipment": [],
            "diet_flags": [],
            "allergen_flags": [],
            "ingredients": [
                {
                    "canonical_ingredient_id": canonical,
                    "qty_fixed_per_batch_base_unit": quantity,
                    "qty_marginal_per_serving_base_unit": "0",
                    "substitutable": False,
                }
            ],
        },
    }


def test_complete_recipe_is_emitted_in_recipe_dto_format():
    imported, review, excluded, report = recipe_import.convert_corpus(
        {"recipes": [_source_recipe()], "summary": {"selected": 1}},
        {"carotte"},
    )

    assert review == []
    assert excluded == []
    assert report["imported_ready"] == 1
    assert imported[0]["id"] == "ricardo_1234_potage_test"
    assert imported[0]["prep_time_fixed_h"] == "0.25"
    assert RecipeDTO(**imported[0]).name == "Potage test"


def test_unknown_quantity_stays_null_and_recipe_goes_to_review():
    imported, review, excluded, report = recipe_import.convert_corpus(
        {
            "recipes": [_source_recipe(status="REVIEW_REQUIRED", quantity=None)],
            "summary": {"selected": 1},
        },
        {"carotte"},
    )

    assert imported == []
    assert excluded == []
    assert report["review_required"] == 1
    assert review[0]["ingredients"][0]["qty_fixed_per_batch_base_unit"] is None


def test_unknown_canonical_id_blocks_active_import():
    imported, review, excluded, report = recipe_import.convert_corpus(
        {"recipes": [_source_recipe(canonical="inconnu")]},
        {"carotte"},
    )

    assert imported == []
    assert excluded == []
    assert len(review) == 1
    assert report["unknown_canonical_ids"] == ["inconnu"]


def test_dessert_category_is_excluded_even_when_recipe_is_complete():
    source = _source_recipe()
    source["souschef_projection"]["tags"]["categories"] = ["Desserts"]
    source["tags"] = {"categories": ["Desserts"]}

    imported, review, excluded, report = recipe_import.convert_corpus(
        {"recipes": [source]}, {"carotte"}
    )

    assert imported == []
    assert review == []
    assert len(excluded) == 1
    assert excluded[0]["tags"]["exclusion_reason"] == "dessert_category:desserts"
    assert report["desserts_excluded"] == 1


def test_curated_dessert_url_catches_source_with_unhelpful_category():
    source = _source_recipe()
    source["source"] = "la_cuisine_de_jean_philippe"
    source["source_url"] = (
        "https://www.lacuisinedejeanphilippe.com/recipe/chausson-la-pomme"
    )
    source["tags"] = {"categories": ["easy"]}

    imported, review, excluded, _report = recipe_import.convert_corpus(
        {"recipes": [source]}, {"carotte"}
    )

    assert imported == []
    assert review == []
    assert excluded[0]["tags"]["exclusion_reason"] == "curated_dessert_url"


def test_production_curation_imports_every_non_dessert_recipe():
    root = SCRIPT.parents[1]
    corpus = json.loads(recipe_import.DEFAULT_SOURCE.read_text(encoding="utf-8"))
    canonical_rows = json.loads(
        (root / "seed/main/canonical_ingredients.json").read_text(encoding="utf-8")
    )
    canonical_catalog = {row["id"]: row for row in canonical_rows}
    curation = json.loads(
        (root / "config/cook_recipe_curation.json").read_text(encoding="utf-8")
    )

    imported, review, excluded, report = recipe_import.convert_corpus(
        corpus,
        set(canonical_catalog),
        canonical_catalog=canonical_catalog,
        curation=curation,
    )

    assert len(imported) == 121
    assert review == []
    assert len(excluded) == 36
    assert report["unknown_canonical_ids"] == []
    assert all(recipe_import._is_complete(recipe) for recipe in imported)
