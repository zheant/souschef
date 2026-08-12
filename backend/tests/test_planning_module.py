"""Tests directs de ``services/planning.py`` (PlanningModule), contre
PostgreSQL réel — complète ``tests/test_api.py`` (contrat HTTP) en couvrant
l'interface de module elle-même, sans passer par FastAPI. Même principe que
``tests/test_substitutability.py`` : contre le vrai solveur PuLP, pas un mock.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from sqlalchemy import delete, select

from app.models import Plan, Price, Product
from app.services import household, planning
from app.solver import PulpMenuSolver, SolverConfig
from tests.db_fixtures import db_session, test_engine, toy_seeded  # noqa: F401

PROFILE_ID = "default"
ON = date(2026, 8, 10)
ALL_ON = {
    "enable_multi_store": True, "enable_batch_fixed_cost": True,
    "enable_salvage": True, "enable_time_cost": True,
    "enable_staples": True, "enable_diversity": True,
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
# Confirmation post-génération : needed_ingredients + finalize_plan (pilote,
# docs/product-pilot.md)
# ---------------------------------------------------------------------------

def test_needed_ingredients_lists_all_with_staple_flag(db_session):
    household.set_staples(db_session, PROFILE_ID, ["riz"])
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(**ALL_ON), PulpMenuSolver()
    )
    by_id = {l.canonical_ingredient_id: l for l in view.needed_ingredients}
    assert set(by_id) == {"riz", "lentille"}  # riz_nature + dahl_toy, R_min=2
    assert by_id["riz"].is_staple is True
    assert by_id["riz"].name == "Riz"
    assert by_id["lentille"].is_staple is False


def test_finalize_plan_locks_the_entire_menu(db_session):
    """finalize_plan ne doit jamais changer les recettes — seulement la
    logistique d'achat, contrairement à reoptimize_plan/Replanifier."""
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(**ALL_ON), PulpMenuSolver()
    )
    servings_before = {m.recipe_id: m.servings for m in view.menu}

    result = planning.finalize_plan(
        db_session, PROFILE_ID, view.id, (), SolverConfig(**ALL_ON), PulpMenuSolver()
    )
    assert result.plan.solver_status == "Optimal"
    assert {m.recipe_id: m.servings for m in result.plan.menu} == servings_before
    assert result.changes is not None
    assert result.changes.added == ()
    assert result.changes.removed == ()


def test_finalize_plan_confirmed_available_ids_removes_need_to_buy(db_session):
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(), PulpMenuSolver()
    )
    assert view.grocery_list_by_store  # riz acheté, config jouet par défaut

    result = planning.finalize_plan(
        db_session, PROFILE_ID, view.id, ("riz",), SolverConfig(), PulpMenuSolver()
    )
    assert result.plan.solver_status == "Optimal"
    assert result.plan.grocery_list_by_store == []


def test_finalize_plan_rejects_an_already_committed_plan(db_session):
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(), PulpMenuSolver()
    )
    planning.commit_plan(db_session, PROFILE_ID, view.id)
    with pytest.raises(planning.PlanAlreadyCommittedError):
        planning.finalize_plan(
            db_session, PROFILE_ID, view.id, (), SolverConfig(), PulpMenuSolver()
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


def test_reoptimize_rejects_an_already_committed_plan(db_session):
    """Une fois accepté, le menu ne doit plus pouvoir changer — sinon les
    achats déjà ajustés pour ce menu se désynchronisent silencieusement du
    nouveau menu."""
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(**ALL_ON), PulpMenuSolver()
    )
    planning.commit_plan(db_session, PROFILE_ID, view.id)
    rid = view.menu[0].recipe_id
    with pytest.raises(planning.PlanAlreadyCommittedError):
        planning.reoptimize_plan(
            db_session, PROFILE_ID, view.id,
            frozenset(), frozenset({rid}), SolverConfig(**ALL_ON), PulpMenuSolver(),
        )


def test_reoptimize_after_a_previously_infeasible_plan_does_not_crash(db_session):
    """Un plan infaisable est persisté tel quel (routes.py le permet
    explicitement) et n'a pas d'objective_terms_cents (None, voir
    _diagnostic_json) — reoptimize_plan ne doit jamais planter dessus si la
    nouvelle tentative réussit cette fois. Simule l'état d'un plan
    précédemment infaisable en mutant directement la ligne persistée plutôt
    que d'essayer de forcer le vrai solveur à échouer (fragile à garantir
    sur ce jeu de données)."""
    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(), PulpMenuSolver()
    )
    plan = db_session.get(Plan, view.id)
    plan.solver_status = "Infeasible"
    plan.diagnostic = {**plan.diagnostic, "objective_terms_cents": None}
    db_session.flush()

    result = planning.reoptimize_plan(
        db_session, PROFILE_ID, view.id,
        frozenset(), frozenset(), SolverConfig(), PulpMenuSolver(),
    )
    assert result.plan.solver_status == "Optimal"
    assert result.changes is None


def test_ingredient_with_no_priced_product_never_reaches_the_solver(db_session):
    """Un ingrédient sans aucun produit prixé (ex. offres expirées, gap de
    scraping) ne doit plus jamais faire planter generate_plan/finalize_plan
    (MissingPriceError, assertion 4) — la recette qui en a besoin est
    exclue au préfiltrage, avant le solveur, comme n'importe quel autre
    filtre dur. Corrige à la source les deux chemins qui tombaient sinon
    sur la même exception non gérée : un ingrédient marqué « à acheter »
    (devrait légitimement échouer, mais proprement) et un ingrédient
    confirmé déjà possédé (ne devrait jamais échouer du tout)."""
    # Retire le prix de l'œuf (une seule recette en dépend, omelette_toy) —
    # contrairement au riz (2 des 3 recettes du jouet), ça laisse riz_nature
    # + dahl_toy, 2 familles, toujours compatible avec R_min=2 du profil
    # jouet par défaut ; pas de rapport avec ce que ce test vérifie.
    oeuf_product_ids = db_session.scalars(
        select(Product.id).where(Product.canonical_ingredient_id == "oeuf")
    ).all()
    db_session.execute(delete(Price).where(Price.product_id.in_(oeuf_product_ids)))
    db_session.flush()

    view = planning.generate_plan(
        db_session, PROFILE_ID, ON, SolverConfig(), PulpMenuSolver()
    )
    assert view.solver_status == "Optimal"
    menu_ids = {m.recipe_id for m in view.menu}
    assert "omelette_toy" not in menu_ids
    assert view.diagnostic["prefilter_counts"]["prix_disponible"] == 2
    assert "oeuf" not in {l.canonical_ingredient_id for l in view.needed_ingredients}

    # Le menu ne dépend plus de l'œuf du tout : finaliser réussit, que
    # l'œuf (absent du besoin) soit ou non listé dans confirmed_available_ids.
    result = planning.finalize_plan(
        db_session, PROFILE_ID, view.id, (), SolverConfig(), PulpMenuSolver(),
    )
    assert result.plan.solver_status == "Optimal"


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
