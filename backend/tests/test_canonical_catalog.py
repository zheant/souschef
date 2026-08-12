"""Invariants du socle versionné d'ingrédients canoniques."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.ingestion.ingredient_curation import normalize_label

SEED = Path(__file__).resolve().parents[2] / "seed" / "main"


def _load(name: str) -> list[dict]:
    return json.loads((SEED / name).read_text(encoding="utf-8"))


def test_catalog_has_unique_purchasable_identities_and_valid_families():
    families = _load("ingredient_families.json")
    ingredients = _load("canonical_ingredients.json")
    family_ids = {row["id"] for row in families}
    ids = [row["id"] for row in ingredients]
    names = [normalize_label(row["name"]) for row in ingredients]

    assert len(families) >= 25
    assert len(ingredients) >= 1000
    assert len(ids) == len(set(ids))
    assert len(names) == len(set(names))
    assert all(re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", iid) for iid in ids)
    assert all(row["family_id"] in family_ids for row in ingredients)

    product_ingredient_ids = {
        row["canonical_ingredient_id"]
        for row in _load("products.json")
    }
    assert product_ingredient_ids <= set(ids)


def test_only_historical_solver_values_and_known_densities_are_populated():
    ingredients = _load("canonical_ingredients.json")
    calibrated = {
        row["id"] for row in ingredients if row["perishability"] is not None
    }
    salvage_calibrated = {
        row["id"]
        for row in ingredients
        if row["salvage_value_cents_per_base_unit"] is not None
    }
    assert len(calibrated) == 23
    assert salvage_calibrated == calibrated
    assert {
        "riz_basmati", "poulet_cuisse", "oeuf", "huile_olive"
    } <= calibrated
    densities = {
        row["id"]: row["density_g_per_ml"]
        for row in ingredients
        if row["density_g_per_ml"] is not None
    }
    assert densities == {
        "lait_325": 1.03,
        "creme_35": 0.98,
        "huile_olive": 0.91,
        "bouillon_poulet": 1.0,
        "sauce_soja": 1.1,
        "eau": 1.0,
    }


def test_aliases_are_bilingual_deterministic_and_point_to_the_catalog():
    ingredients = _load("canonical_ingredients.json")
    aliases = _load("canonical_ingredient_aliases.json")
    ingredient_ids = {row["id"] for row in ingredients}
    keys = [
        (row["language"], row["normalized_alias"])
        for row in aliases
    ]

    assert {row["language"] for row in aliases} == {"en", "fr"}
    assert len(keys) == len(set(keys))
    assert all(row["canonical_ingredient_id"] in ingredient_ids for row in aliases)
    assert all(
        row["normalized_alias"] == normalize_label(row["alias"])
        for row in aliases
    )
    english_targets = {
        row["canonical_ingredient_id"]
        for row in aliases
        if row["language"] == "en"
    }
    assert english_targets == ingredient_ids

    owners_by_label: dict[str, set[str]] = {}
    for ingredient in ingredients:
        owners_by_label.setdefault(
            normalize_label(ingredient["name"]), set()
        ).add(ingredient["id"])
    for alias in aliases:
        owners_by_label.setdefault(alias["normalized_alias"], set()).add(
            alias["canonical_ingredient_id"]
        )
    assert all(len(owners) == 1 for owners in owners_by_label.values())
