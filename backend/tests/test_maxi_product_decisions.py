"""Intégrité du manifeste de titres commerciaux Maxi."""

import json
from pathlib import Path

from app.ingestion.ingredient_curation import normalize_label


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_every_normalized_indexed_title_has_one_decision():
    source = _read("data/catalogue-registry/maxi-indexed-titles.json")
    report = _read("config/maxi-title-decisions.json")
    expected = {normalize_label(title) for title in source["titles"]}
    observed = {normalize_label(row["product_name"]) for row in report["decisions"]}

    assert expected == observed
    assert len(report["decisions"]) == len(observed) == report["product_count"]
    assert sum(report["counts"].values()) == report["product_count"]


def test_title_rules_cover_every_final_decision_and_use_valid_canonicals():
    report = _read("config/maxi-title-decisions.json")
    overrides = _read("config/maxi-title-match-overrides.json")
    canonical_ids = {row["id"] for row in _read("seed/main/canonical_ingredients.json")}
    final_titles = {
        normalize_label(row["product_name"])
        for row in report["decisions"]
        if row["action"] != "canonical_gap"
    }

    assert {row["normalized_title"] for row in overrides} == final_titles
    for row in overrides:
        if row["status"] == "approved":
            assert row["canonical_ingredient_id"] in canonical_ids
        else:
            assert row["status"] == "rejected"
            assert "canonical_ingredient_id" not in row


def test_remaining_gaps_are_explicit_and_not_silently_rejected():
    report = _read("config/maxi-title-decisions.json")
    gaps = _read("data/catalogue-registry/maxi-title-canonical-gaps.json")
    overrides = _read("config/maxi-title-match-overrides.json")
    gap_titles = {normalize_label(row["product_name"]) for row in gaps}

    assert gap_titles == {
        normalize_label(row["product_name"])
        for row in report["decisions"]
        if row["action"] == "canonical_gap"
    }
    assert gap_titles.isdisjoint({row["normalized_title"] for row in overrides})
