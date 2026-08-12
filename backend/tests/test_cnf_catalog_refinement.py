"""Qualité et traçabilité du lot FCÉN promu dans le seed principal."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from app.ingestion.ingredient_curation import normalize_label

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "seed" / "main"
sys.path.insert(0, str(ROOT / "scripts"))

from refine_cnf_catalog import quality_reason  # noqa: E402


def _load(name: str):
    return json.loads((SEED / name).read_text(encoding="utf-8"))


def test_refinement_accounts_for_every_source_row_and_only_accepts_safe_actions():
    batch = _load("cnf_catalog_curation.json")
    decisions = batch["decisions"]
    counts = batch["reason_counts"]

    assert batch["source_version"] == "2026"
    assert batch["archive_sha256"] == (
        "F5FAAD8977EE6BBDD9D69C8649077CACD87D8658AD200509A4047DB1E29EDCDD"
    )
    assert batch["source_row_count"] == 5993
    assert sum(counts.values()) == batch["source_row_count"]
    assert len(decisions) == (
        counts["accepted_attach_exact"]
        + counts["accepted_attach_curated_override"]
        + counts["accepted_create_variant"]
        + counts["accepted_create_reviewed_similar"]
    )
    assert {row["action"] for row in decisions} == {
        "attach_existing",
        "create_variant",
    }
    assert len({row["food_code"] for row in decisions}) == len(decisions)
    assert counts["accepted_create_reviewed_similar"] > 0
    assert counts["reviewed_similarity_excluded"] > 0


def test_quality_gate_rejects_cooked_plurals_and_accepts_explicit_purchase_states():
    base = {
        "cnf_food_group_code": "11",
        "food_description_fr": "Courgettes, bouillies, égouttées",
        "food_description_en": "Zucchini, boiled, drained",
    }
    assert quality_reason(base) == "cooked_seasoned_or_composite"

    raw = {
        **base,
        "food_description_fr": "Courgette, crue",
        "food_description_en": "Zucchini, raw",
    }
    assert quality_reason(raw) is None

    frozen = {
        **base,
        "food_description_fr": "Artichaut, congelé, non préparé",
        "food_description_en": "Artichoke, frozen, unprepared",
    }
    assert quality_reason(frozen) is None


def test_created_variants_keep_unknown_business_values_null_and_are_bilingual():
    decisions = _load("cnf_catalog_curation.json")["decisions"]
    creates = [row for row in decisions if row["action"] == "create_variant"]

    assert len(creates) >= 250
    for decision in creates:
        canonical = decision["canonical"]
        assert canonical["perishability"] is None
        assert canonical["salvage_value_cents_per_base_unit"] is None
        assert canonical["density_g_per_ml"] is None
        assert canonical["base_unit"] in {"g", "ml", "unit"}
        assert len(canonical["name"]) <= 120
        assert decision["aliases"] == [
            {
                "language": "en",
                "alias": decision["aliases"][0]["alias"],
            }
        ]
        assert normalize_label(decision["aliases"][0]["alias"])


def test_similar_names_are_acknowledged_and_reviewed_animal_rows_are_bounded():
    decisions = _load("cnf_catalog_curation.json")["decisions"]
    by_code = {row["food_code"]: row for row in decisions}
    reviewed_similar = [
        row for row in decisions
        if row["action"] == "create_variant"
        and row["acknowledged_similar_ids"]
    ]

    assert reviewed_similar
    assert all(row["acknowledged_similar_ids"] for row in reviewed_similar)
    assert by_code["88"]["canonical"]["id"] == "oeuf_de_canard"
    assert by_code["88"]["canonical"]["base_unit"] == "unit"
    assert by_code["2653"]["canonical"]["id"] == "coeur_de_boeuf"
    assert "560" not in by_code  # aucune promotion générale du groupe volaille


def test_integrated_crosswalks_and_events_are_complete_and_reproducible():
    batch = _load("cnf_catalog_curation.json")
    ingredients = _load("canonical_ingredients.json")
    refs = _load("canonical_ingredient_external_refs.json")
    events = _load("ingredient_curation_events.json")
    ids = {row["id"] for row in ingredients}

    assert len(refs) == len(events) == len(batch["decisions"])
    assert len({(r["source"], r["external_id"], r["source_version"]) for r in refs}) == len(refs)
    assert len({event["decision_fingerprint"] for event in events}) == len(events)
    assert all(ref["canonical_ingredient_id"] in ids for ref in refs)
    assert all(event["canonical_ingredient_id"] in ids for event in events)

    for event in events:
        expected = hashlib.sha256(
            json.dumps(
                event["decision_payload"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest().upper()
        assert event["decision_fingerprint"] == expected


def test_known_duplicates_are_attached_instead_of_created():
    decisions = {
        row["food_code"]: row
        for row in _load("cnf_catalog_curation.json")["decisions"]
    }
    assert decisions["3252"]["canonical_ingredient_id"] == "haricot_noir_sec"
    assert decisions["4460"]["canonical_ingredient_id"] == "pate_soba"
    assert "canonical" not in decisions["3252"]
    assert "canonical" not in decisions["4460"]
