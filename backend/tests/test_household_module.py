"""Tests directs de ``services/household.py`` (HouseholdModule), contre
PostgreSQL réel — complète ``tests/test_api.py`` (contrat HTTP)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services import household
from tests.db_fixtures import db_session, test_engine, toy_seeded  # noqa: F401

PROFILE_ID = "default"


def test_get_profile_not_found(db_session):
    with pytest.raises(household.ProfileNotFound):
        household.get_profile(db_session, "inexistant")


def test_get_and_update_profile(db_session):
    view = household.get_profile(db_session, PROFILE_ID)
    assert view.id == PROFILE_ID
    assert (view.demand["borne_basse"], view.demand["borne_haute"]) == (4, 5)

    updated = household.update_profile(
        db_session, PROFILE_ID, {"meals_per_horizon": 6}
    )
    assert Decimal(updated.demand["D_exact"]) == Decimal("6")
    household.update_profile(db_session, PROFILE_ID, {"meals_per_horizon": 4})


def test_pantry_roundtrip_and_unknown_ingredient(db_session):
    lines = household.update_pantry(
        db_session, PROFILE_ID,
        [{"canonical_ingredient_id": "riz", "quantity_base_unit": 120}],
    )
    assert any(
        line.canonical_ingredient_id == "riz"
        and Decimal(line.quantity_base_unit) == 120
        for line in lines
    )
    assert household.get_pantry(db_session, PROFILE_ID) == lines

    with pytest.raises(household.UnknownIngredientError):
        household.update_pantry(
            db_session, PROFILE_ID,
            [{"canonical_ingredient_id": "inexistant", "quantity_base_unit": 1}],
        )


def test_set_pantry_priority_and_unknown_ingredient(db_session):
    line = household.set_pantry_priority(db_session, PROFILE_ID, "riz", "must_use")
    assert line.priority == "must_use"
    assert line.quantity_base_unit == "0.000"  # ligne neuve, quantité par défaut

    with pytest.raises(household.UnknownIngredientError):
        household.set_pantry_priority(db_session, PROFILE_ID, "inexistant", "must_use")


def test_update_pantry_never_resets_priority(db_session):
    """Piège identifié en conception : PUT /api/pantry (quantité) est aussi
    appelé par la confirmation en deux temps de Génération, qui n'envoie
    jamais de priorité — il ne doit jamais écraser un « doit être utilisé »
    déjà posé."""
    household.update_pantry(
        db_session, PROFILE_ID,
        [{"canonical_ingredient_id": "riz", "quantity_base_unit": 100}],
    )
    household.set_pantry_priority(db_session, PROFILE_ID, "riz", "must_use")

    lines = household.update_pantry(
        db_session, PROFILE_ID,
        [{"canonical_ingredient_id": "riz", "quantity_base_unit": 250}],
    )
    riz = next(l for l in lines if l.canonical_ingredient_id == "riz")
    assert riz.quantity_base_unit == "250.000"
    assert riz.priority == "must_use"
