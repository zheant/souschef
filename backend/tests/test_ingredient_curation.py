"""Curation FCÉN : dédoublonnage, audit et famille descriptive riz."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.ingestion.ingredient_curation import (
    AliasSpec,
    CanonicalSpec,
    CurationDecision,
    DuplicateCanonicalError,
    SimilarCandidatesNeedReview,
    apply_decision,
    label_similarity,
    normalize_label,
    preview_candidate,
)
from app.models import (
    CanonicalIngredient,
    CanonicalIngredientAlias,
    CanonicalIngredientExternalRef,
    CnfFoodCandidate,
    IngredientCandidateStatus,
    IngredientCurationAction,
    IngredientCurationEvent,
    Product,
    UnitKind,
)
from tests.db_fixtures import db_session, test_engine, toy_seeded  # noqa: F401


def _candidate(code: str, name_fr: str, *, alternate_fr: str | None = None):
    return CnfFoodCandidate(
        source_version="test-2026",
        archive_sha256="A" * 64,
        food_code=code,
        food_description_en="Rice test candidate",
        food_description_fr=name_fr,
        alternate_description_en=None,
        alternate_description_fr=alternate_fr,
        food_source_code=None,
        usda_ndb_code=None,
        cnf_food_group_code="20",
        cnf_food_group_description_en="Cereal Grains and Pasta",
        cnf_food_group_description_fr="Céréales et pâtes alimentaires",
        comment_en=None,
        comment_fr=None,
        scientific_name=None,
        food_last_updated_date="2026-01-01",
        raw_payload={"Food_Code": code},
        curation_status=IngredientCandidateStatus.candidate,
    )


def _decision(code: str, **overrides) -> CurationDecision:
    values = {
        "source_version": "test-2026",
        "food_code": code,
        "action": IngredientCurationAction.attach_existing,
        "canonical_ingredient_id": "riz",
        "reviewer": "curateur@test",
        "rationale": "Même ingrédient vendable que le canon existant.",
    }
    values.update(overrides)
    return CurationDecision(**values)


def test_normalization_is_accent_case_and_punctuation_insensitive():
    assert normalize_label("  ŒUF—entier, cru! ") == "oeuf entier cru"
    assert normalize_label("ÉPINARDS frais") == "epinards frais"
    assert label_similarity("Riz basmati", "riz basmati") == 1
    assert label_similarity("Riz basmati", "Riz basmati, cuit") >= 0.95


def test_attach_is_audited_and_idempotent(db_session):
    candidate = _candidate("9001", "Riz blanc")
    db_session.add(candidate)
    db_session.flush()
    decision = _decision(
        "9001", aliases=(AliasSpec(language="fr", alias="Riz blanc"),)
    )

    first = apply_decision(db_session, decision)
    second = apply_decision(db_session, decision)

    assert first.replayed is False
    assert second.replayed is True
    assert second.event_id == first.event_id
    assert candidate.curation_status == IngredientCandidateStatus.approved
    assert candidate.reviewed_by == "curateur@test"
    assert db_session.scalar(
        select(func.count()).select_from(IngredientCurationEvent).where(
            IngredientCurationEvent.external_id == "9001"
        )
    ) == 1
    ref = db_session.scalar(
        select(CanonicalIngredientExternalRef).where(
            CanonicalIngredientExternalRef.external_id == "9001"
        )
    )
    assert ref.canonical_ingredient_id == "riz"
    alias = db_session.scalar(
        select(CanonicalIngredientAlias).where(
            CanonicalIngredientAlias.normalized_alias == "riz blanc"
        )
    )
    assert alias.confirmed_by == "curateur@test"


def test_exact_canonical_name_blocks_a_duplicate_variant(db_session):
    candidate = _candidate("9002", "RÍZ")
    db_session.add(candidate)
    db_session.flush()
    decision = _decision(
        "9002",
        action=IngredientCurationAction.create_variant,
        canonical_ingredient_id=None,
        canonical=CanonicalSpec(
            id="riz_copie",
            family_id="riz",
            name="Riz",
            unit_kind=UnitKind.mass,
            base_unit="g",
            perishability=Decimal("0.02"),
            salvage_value_cents_per_base_unit=Decimal("0.1"),
        ),
    )

    with pytest.raises(DuplicateCanonicalError, match="attach_existing"):
        apply_decision(db_session, decision)


def test_similar_name_is_flagged_and_never_auto_merged(db_session):
    db_session.add(
        CanonicalIngredient(
            id="riz_basmati_test",
            family_id="riz",
            name="Riz basmati",
            unit_kind=UnitKind.mass,
            base_unit="g",
            perishability=Decimal("0.02"),
            salvage_value_cents_per_base_unit=Decimal("0.1"),
        )
    )
    candidate = _candidate("9003", "Riz basmati parfumé")
    db_session.add(candidate)
    db_session.flush()
    decision = _decision(
        "9003",
        action=IngredientCurationAction.create_variant,
        canonical_ingredient_id=None,
        canonical=CanonicalSpec(
            id="riz_parfume_test",
            family_id="riz",
            name="Riz parfumé de test",
            unit_kind=UnitKind.mass,
            base_unit="g",
            perishability=Decimal("0.02"),
            salvage_value_cents_per_base_unit=Decimal("0.1"),
        ),
    )

    with pytest.raises(SimilarCandidatesNeedReview, match="riz_basmati_test"):
        apply_decision(db_session, decision)
    assert db_session.get(CanonicalIngredient, "riz_parfume_test") is None


def test_rice_family_keeps_variants_distinct_from_retail_products(db_session):
    candidate = _candidate("9004", "Riz jasmin")
    db_session.add(candidate)
    db_session.flush()
    decision = _decision(
        "9004",
        action=IngredientCurationAction.create_variant,
        canonical_ingredient_id=None,
        canonical=CanonicalSpec(
            id="riz_jasmin_test",
            family_id="riz",
            name="Riz jasmin",
            unit_kind=UnitKind.mass,
            base_unit="g",
            perishability=Decimal("0.02"),
            salvage_value_cents_per_base_unit=Decimal("0.1"),
        ),
        aliases=(AliasSpec(language="en", alias="Jasmine rice"),),
    )

    result = apply_decision(db_session, decision)
    created = db_session.get(CanonicalIngredient, "riz_jasmin_test")
    existing = db_session.get(CanonicalIngredient, "riz")

    assert result.canonical_ingredient_id == "riz_jasmin_test"
    assert created.family_id == existing.family_id == "riz"
    assert created.id != existing.id
    # Les références d'épicerie restent sur une identité canonique précise,
    # jamais sur la famille descriptive.
    assert db_session.scalar(
        select(func.count()).select_from(Product).where(
            Product.canonical_ingredient_id == "riz_jasmin_test"
        )
    ) == 0
    assert db_session.scalar(
        select(func.count()).select_from(Product).where(
            Product.canonical_ingredient_id == "riz"
        )
    ) > 0


def test_preview_uses_approved_aliases_and_exclusion_is_audited(db_session):
    candidate = _candidate("9005", "Riz blanc", alternate_fr="Riz nature")
    db_session.add(candidate)
    db_session.flush()
    db_session.add(
        CanonicalIngredientAlias(
            canonical_ingredient_id="riz",
            language="fr",
            alias="Riz nature",
            normalized_alias="riz nature",
            source="manual",
            confirmed_by="test",
        )
    )
    db_session.flush()

    preview = preview_candidate(db_session, "test-2026", "9005")
    assert [match.canonical_ingredient_id for match in preview.exact_matches] == [
        "riz"
    ]

    excluded = apply_decision(
        db_session,
        _decision(
            "9005",
            action=IngredientCurationAction.exclude,
            canonical_ingredient_id=None,
            rationale="Plat préparé, pas un ingrédient achetable de recette.",
        ),
    )
    assert excluded.canonical_ingredient_id is None
    assert candidate.curation_status == IngredientCandidateStatus.rejected
    event = db_session.get(IngredientCurationEvent, excluded.event_id)
    assert event.candidate_snapshot["food_description_fr"] == "Riz blanc"
