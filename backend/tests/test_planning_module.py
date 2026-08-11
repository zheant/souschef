"""Tests directs de ``services/planning.py`` (PlanningModule), contre
PostgreSQL réel — complète ``tests/test_api.py`` (contrat HTTP) en couvrant
l'interface de module elle-même, sans passer par FastAPI. Même principe que
``tests/test_substitutability.py`` : contre le vrai solveur PuLP, pas un mock.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from sqlalchemy import select

from app.models import CanonicalIngredient, Price, Product, UnitKind
from app.services import household, planning
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


# ---------------------------------------------------------------------------
# Périssables prioritaires ou obligatoires (pilote, docs/product-pilot.md)
# ---------------------------------------------------------------------------

def test_generate_plan_respects_must_use_pantry(db_session):
    household.update_pantry(
        db_session, PROFILE_ID,
        [{"canonical_ingredient_id": "lentille", "quantity_base_unit": 300}],
    )
    household.set_pantry_priority(db_session, PROFILE_ID, "lentille", "must_use")

    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(**ALL_ON), PulpMenuSolver()
    )
    assert view.solver_status == "Optimal"
    dahl = next((m.servings for m in view.menu if m.recipe_id == "dahl_toy"), 0)
    assert 70 * dahl >= 150  # 0,5 × 300 g déclarés


def test_must_use_pantry_ingredient_with_no_compatible_recipe_is_rejected(db_session):
    # Ingrédient synthétique qu'aucune recette du jouet ne référence.
    db_session.add(CanonicalIngredient(
        id="epice_test", name="Épice de test", unit_kind=UnitKind.mass,
        base_unit="g", perishability=Decimal("0"),
        salvage_value_cents_per_base_unit=Decimal("0"),
    ))
    db_session.flush()
    household.update_pantry(
        db_session, PROFILE_ID,
        [{"canonical_ingredient_id": "epice_test", "quantity_base_unit": 50}],
    )
    household.set_pantry_priority(db_session, PROFILE_ID, "epice_test", "must_use")

    with pytest.raises(planning.PantryIngredientNotUsableError):
        planning.generate_plan(
            db_session, PROFILE_ID, ON, SolverConfig(**ALL_ON), PulpMenuSolver()
        )


# ---------------------------------------------------------------------------
# Rabais et économies dans la liste d'épicerie (pilote,
# docs/product-pilot.md)
# ---------------------------------------------------------------------------

def test_grocery_line_has_no_savings_without_a_promo(db_session):
    """Le seed jouet n'a aucune promotion (vérifié : toutes les offres ont
    is_promo=false, regular_price_cents_cad == price_cents_cad) — le
    branchement ne doit rien changer par défaut."""
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(), PulpMenuSolver()
    )
    line = view.grocery_list_by_store[0]["lines"][0]
    assert line["is_promo"] is False
    assert line["regular_price_cents_cad"] == line["unit_price_cents_cad"]
    assert line["savings_cents_cad"] is None
    assert Decimal(view.grocery_list_by_store[0]["savings_cents_cad"]) == 0


def test_pantry_lines_resolved_with_name_and_priority(db_session):
    """Garde-manger itemisé (pilote, docs/product-pilot.md) —
    ``diagnostic.pantry_consumed_by_ingredient`` existait déjà mais n'était
    jamais résolu en nom nulle part avant ce chantier."""
    household.update_pantry(
        db_session, PROFILE_ID,
        [{"canonical_ingredient_id": "riz", "quantity_base_unit": 100}],
    )
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(**ALL_ON), PulpMenuSolver()
    )
    by_id = {l.canonical_ingredient_id: l for l in view.pantry_lines}
    assert "riz" in by_id
    riz = by_id["riz"]
    assert riz.name == "Riz"
    assert riz.base_unit == "g"
    assert riz.priority == "normal"
    assert Decimal(riz.quantity_base_unit) > 0
    assert Decimal(riz.quantity_base_unit) <= 100  # jamais plus que le stock déclaré


def test_commit_with_buy_instead_picks_cheapest_product_and_spares_stock(db_session):
    """Test discriminant : riz a deux produits au jouet à des prix par unité
    de base différents (riz_1kg = 0,30 ¢/g, riz_400g = 0,45 ¢/g) — la
    résolution doit choisir riz_1kg, pas le premier trouvé. Construit un
    ``Plan`` directement (pas via le solveur) pour isoler la comptabilité de
    ``_apply_commit`` de la décision d'optimisation elle-même — même esprit
    que les tests synthétiques de ``test_solver_toy.py``."""
    from app.models import Plan, PlanStatus

    household.update_pantry(
        db_session, PROFILE_ID,
        [{"canonical_ingredient_id": "riz", "quantity_base_unit": 100}],
    )
    plan = Plan(
        household_profile_id=PROFILE_ID, status=PlanStatus.proposed,
        on_date=ON, solver_status="Optimal",
        config={"enable_pantry_stock": True},
        servings={}, cooked={}, purchases=[],
        ingredient_needs={"riz": "100"},
        stores_visited=[], diagnostic={},
    )
    db_session.add(plan)
    db_session.flush()

    result = planning.commit_plan(
        db_session, PROFILE_ID, plan.id, frozenset({"riz"})
    )
    assert result.status == "committed"
    # « à acheter » force consommé=0 : 100 (stock, inchangé) + 1000 (le
    # paquet riz_1kg acheté) − 100 (besoin) = 1000 — le stock déclaré n'est
    # jamais décrémenté pour un ingrédient que l'utilisateur dit ne pas avoir.
    assert Decimal(result.pantry_after_commit["riz"]) == Decimal(1000)

    fetched = planning.get_plan(db_session, PROFILE_ID, plan.id)
    lines = [l for g in fetched.grocery_list_by_store for l in g["lines"]]
    assert len(lines) == 1
    assert lines[0]["product_external_key"] == "riz_1kg"  # le moins cher, pas riz_400g
    assert Decimal(lines[0]["taxed_total_cents_cad"]) == Decimal("300.00")


def test_commit_buy_instead_rejects_unknown_ingredient(db_session):
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(), PulpMenuSolver()
    )
    with pytest.raises(planning.UnknownBuyInsteadIngredientError):
        planning.commit_plan(
            db_session, PROFILE_ID, view.id, frozenset({"ingredient_inexistant"})
        )


def test_grocery_line_reports_savings_on_a_real_promo(db_session):
    """Test discriminant : mute directement la ligne market.price déjà
    chargée par le seed (pas d'insertion en conflit avec la contrainte
    unique existante), régénère, vérifie le calcul taxé des économies."""
    riz_id = db_session.scalar(
        select(Product.id).where(Product.external_key == "riz_400g")
    )
    price_row = db_session.scalar(
        select(Price).where(
            Price.product_id == riz_id,
            Price.valid_from <= ON, Price.valid_to >= ON,
        )
    )
    price_row.is_promo = True
    price_row.regular_price_cents_cad = price_row.price_cents_cad + 40
    db_session.flush()

    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(), PulpMenuSolver()
    )
    line = next(
        l for g in view.grocery_list_by_store for l in g["lines"]
        if l["product_external_key"] == "riz_400g"
    )
    assert line["is_promo"] is True
    assert line["regular_price_cents_cad"] == price_row.price_cents_cad + 40
    expected = (
        Decimal(40) * line["units"]
        * (1 + db_session.get(Product, riz_id).tax_rate)
    ).quantize(Decimal("0.01"))
    assert Decimal(line["savings_cents_cad"]) == expected
    assert Decimal(view.grocery_list_by_store[0]["savings_cents_cad"]) == expected
