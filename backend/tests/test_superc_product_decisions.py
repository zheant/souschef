"""Intégrité du manifeste exhaustif de curation Super C."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_every_registry_product_has_exactly_one_curation_decision():
    registry = _read("data/catalogue-registry/superc.json")
    report = _read("config/superc-product-decisions.json")
    registry_ids = [row["source_product_id"] for row in registry["products"]]
    decision_ids = [row["source_product_id"] for row in report["decisions"]]
    assert len(decision_ids) == len(set(decision_ids)) == report["product_count"]
    assert set(decision_ids) == set(registry_ids)
    assert sum(report["counts"].values()) == report["product_count"]


def test_active_overrides_are_safe_and_reference_existing_canonicals():
    report = _read("config/superc-product-decisions.json")
    overrides = _read("config/superc-match-overrides.json")
    reviewed = _read("config/superc-reviewed-overrides.json")
    canonical_ids = {
        row["id"] for row in _read("seed/main/canonical_ingredients.json")
    }
    final_ids = {
        row["source_product_id"]
        for row in report["decisions"]
        if row["action"] != "canonical_gap"
    }
    reviewed_ids = {row["source_product_id"] for row in reviewed}
    assert {row["source_product_id"] for row in overrides} == final_ids | reviewed_ids
    for row in overrides:
        if row["status"] == "approved":
            assert row["canonical_ingredient_id"] in canonical_ids
        else:
            assert row["status"] == "rejected"
            assert "canonical_ingredient_id" not in row


def test_no_out_of_scope_category_is_approved():
    """Un rayon hors périmètre n'admet qu'une identité exacte ou une revue humaine.

    La raison d'une revue humaine est un texte libre : c'est précisément là que
    la décision s'explique, et la figer à une poignée de mots interdirait de
    dire pourquoi le produit a été retenu. Ce qui doit rester vérifiable, c'est
    sa provenance — une décision consignée dans
    ``superc-reviewed-overrides.json`` — jamais une heuristique de
    rapprochement qui se serait glissée dans ces rayons.
    """
    report = _read("config/superc-product-decisions.json")
    forbidden = ("/boissons/", "/collations/", "/plats-cuisines/", "/repas-et-plats-d-accompagnement/")
    for row in report["decisions"]:
        if row["action"] == "link_existing" and any(
            part in row["category_url"] for part in forbidden
        ):
            if row["reason"] == "existing_exact_match":
                continue
            assert row["confidence"] == "human_review", row
            assert row["evidence"] == ["superc-match-overrides.json"], row
