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


def test_staples_roundtrip_and_unknown_ingredient(db_session):
    lines = household.set_staples(db_session, PROFILE_ID, ["riz", "lentille"])
    assert {l.canonical_ingredient_id for l in lines} == {"riz", "lentille"}
    assert household.get_staples(db_session, PROFILE_ID) == lines

    with pytest.raises(household.UnknownIngredientError):
        household.set_staples(db_session, PROFILE_ID, ["inexistant"])


def test_set_staples_replaces_the_full_set(db_session):
    """Pas un upsert ligne par ligne comme l'ancien garde-manger — la liste
    est remplacée comme un tout à chaque appel."""
    household.set_staples(db_session, PROFILE_ID, ["riz", "lentille"])
    lines = household.set_staples(db_session, PROFILE_ID, ["oeuf"])
    assert {l.canonical_ingredient_id for l in lines} == {"oeuf"}
    assert household.get_staples(db_session, PROFILE_ID) == lines

    empty = household.set_staples(db_session, PROFILE_ID, [])
    assert empty == ()
    assert household.get_staples(db_session, PROFILE_ID) == ()
