"""Tests directs de ``services/planning.py`` (PlanningModule), contre
PostgreSQL réel — complète ``tests/test_api.py`` (contrat HTTP) en couvrant
l'interface de module elle-même, sans passer par FastAPI. Même principe que
``tests/test_substitutability.py`` : contre le vrai solveur PuLP, pas un mock.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services import planning
from app.solver import PulpMenuSolver, SolverConfig
from tests.db_fixtures import db_session, test_engine, toy_seeded  # noqa: F401

PROFILE_ID = "default"
ON = date(2026, 8, 10)


def test_generate_get_and_commit_plan(db_session):
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(), PulpMenuSolver()
    )
    assert view.solver_status == "Optimal"
    # Config par défaut (jouet) : menu monotone attendu, riz ×5 (voir
    # tests/test_api.py::test_plan_create_fetch_and_grocery_grouping).
    assert view.menu[0].recipe_id == "riz_nature"

    fetched = planning.get_plan(db_session, PROFILE_ID, view.id)
    assert fetched.id == view.id
    assert fetched.grocery_list_by_store == view.grocery_list_by_store

    with pytest.raises(planning.PlanNotFound):
        planning.get_plan(db_session, PROFILE_ID, 999_999)

    result = planning.commit_plan(db_session, PROFILE_ID, view.id)
    assert result.status == "committed"
    assert all(Decimal(v) >= 0 for v in result.pantry_after_commit.values())

    # Double commit refusé (même comportement que POST /plan/{id}/commit).
    with pytest.raises(planning.PlanNotCommittable):
        planning.commit_plan(db_session, PROFILE_ID, view.id)


def test_plan_is_scoped_to_its_owning_profile(db_session):
    """Vérification de propriété : un plan d'un profil n'est pas visible pour
    un autre — c'était dupliqué dans get_plan/post_commit avant le refactor,
    centralisé maintenant dans _load_owned_plan."""
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(), PulpMenuSolver()
    )
    with pytest.raises(planning.PlanNotFound):
        planning.get_plan(db_session, "un_autre_profil", view.id)
    with pytest.raises(planning.PlanNotFound):
        planning.commit_plan(db_session, "un_autre_profil", view.id)
