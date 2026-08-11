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
ALL_ON = {
    "enable_multi_store": True, "enable_batch_fixed_cost": True,
    "enable_salvage": True, "enable_time_cost": True,
    "enable_pantry_stock": True, "enable_diversity": True,
}


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


# ---------------------------------------------------------------------------
# Verrouillage / remplacement / réoptimisation expliquée (pilote,
# docs/product-pilot.md)
# ---------------------------------------------------------------------------

def test_reoptimize_locks_exact_servings_and_excludes_recipe(db_session):
    """Le scénario « remplacer » : verrouiller toutes les autres recettes du
    plan + exclure celle visée + réoptimiser — un seul mécanisme, la portion
    laissée vacante par l'exclusion est comblée par le solveur."""
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(**ALL_ON), PulpMenuSolver()
    )
    servings_by_recipe = {m.recipe_id: m.servings for m in view.menu}
    assert set(servings_by_recipe) == {"riz_nature", "dahl_toy"}  # R_min=2, jouet

    result = planning.reoptimize_plan(
        db_session, PROFILE_ID, view.id,
        frozenset({"riz_nature"}), frozenset({"dahl_toy"}),
        SolverConfig(**ALL_ON), PulpMenuSolver(),
    )
    assert result.plan.solver_status == "Optimal"
    new_servings = {m.recipe_id: m.servings for m in result.plan.menu}
    assert new_servings["riz_nature"] == servings_by_recipe["riz_nature"]
    assert "dahl_toy" not in new_servings

    assert result.changes is not None
    assert result.changes.removed == ("dahl_toy",)
    assert "riz_nature" not in result.changes.added
    assert "riz_nature" not in result.changes.removed
    # Le plan réoptimisé est un NOUVEAU plan persisté, pas une mutation.
    assert result.plan.id != view.id


def test_reoptimize_broader_uses_only_explicit_locks(db_session):
    """« Réoptimisation plus large » : seules les recettes explicitement
    verrouillées le sont — pas d'exclusion, le reste est libre."""
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(**ALL_ON), PulpMenuSolver()
    )
    riz_servings = next(m.servings for m in view.menu if m.recipe_id == "riz_nature")

    result = planning.reoptimize_plan(
        db_session, PROFILE_ID, view.id,
        frozenset({"riz_nature"}), frozenset(),
        SolverConfig(**ALL_ON), PulpMenuSolver(),
    )
    assert result.plan.solver_status == "Optimal"
    new_riz = next(
        m.servings for m in result.plan.menu if m.recipe_id == "riz_nature"
    )
    assert new_riz == riz_servings


def test_reoptimize_lock_on_recipe_not_in_plan_is_rejected(db_session):
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(**ALL_ON), PulpMenuSolver()
    )
    with pytest.raises(planning.RecipeNotInPlanError):
        planning.reoptimize_plan(
            db_session, PROFILE_ID, view.id,
            frozenset({"omelette_toy"}), frozenset(),
            SolverConfig(**ALL_ON), PulpMenuSolver(),
        )


def test_reoptimize_conflicting_lock_and_exclude_is_rejected(db_session):
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(**ALL_ON), PulpMenuSolver()
    )
    rid = view.menu[0].recipe_id
    with pytest.raises(planning.ConflictingRecipeSelectionError):
        planning.reoptimize_plan(
            db_session, PROFILE_ID, view.id,
            frozenset({rid}), frozenset({rid}),
            SolverConfig(**ALL_ON), PulpMenuSolver(),
        )


def test_reoptimize_is_scoped_to_its_owning_profile(db_session):
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(**ALL_ON), PulpMenuSolver()
    )
    with pytest.raises(planning.PlanNotFound):
        planning.reoptimize_plan(
            db_session, "un_autre_profil", view.id,
            frozenset(), frozenset(), SolverConfig(**ALL_ON), PulpMenuSolver(),
        )


# ---------------------------------------------------------------------------
# Confirmation du garde-manger en deux temps (pilote, docs/product-pilot.md)
# ---------------------------------------------------------------------------

def test_pantry_prompt_prioritizes_ingredients_of_the_plan(db_session):
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(**ALL_ON), PulpMenuSolver()
    )
    prompt = planning.pantry_prompt(db_session, PROFILE_ID, view.id)
    assert prompt  # riz_nature + dahl_toy au menu : au moins riz et lentille

    by_id = {l.canonical_ingredient_id: l for l in prompt}
    assert "riz" in by_id
    riz = by_id["riz"]
    assert riz.name == "Riz"
    assert riz.unit_kind == "mass" and riz.base_unit == "g"
    assert Decimal(riz.needed_quantity_base_unit) > 0
    assert Decimal(riz.estimated_cost_cents) > 0

    # Trié par coût estimé décroissant.
    costs = [Decimal(l.estimated_cost_cents) for l in prompt]
    assert costs == sorted(costs, reverse=True)


def test_pantry_prompt_is_scoped_to_its_owning_profile(db_session):
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(**ALL_ON), PulpMenuSolver()
    )
    with pytest.raises(planning.PlanNotFound):
        planning.pantry_prompt(db_session, "un_autre_profil", view.id)
