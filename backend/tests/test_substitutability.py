"""Tests de substituabilité des interfaces déclarées remplaçables.

Le principe : pour chaque interface — MenuSolver, AppetenceScorer,
CircularPort, RecipeSourcePort — injecter une implémentation FACTICE et
prouver qu'**aucune implémentation concrète n'est atteinte** (l'implémentation
concrète est piégée par monkeypatch : l'atteindre fait échouer le test).

C'est le seul type de test qui protège la promesse centrale de la v1 :
brancher un vrai scraper et 1000 vraies recettes sans toucher au solveur, à
l'API ni au front-end. Le RuleBasedAppetenceScorer codé en dur dans le
solveur (trouvé par accident au point de contrôle de l'étape 4) est
exactement la régression que ces tests interdisent désormais.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.appetence import RuleBasedAppetenceScorer, UtilitySegment
from app.services.prefilter import prefilter_recipes
from app.solver import PulpMenuSolver, SolverConfig
from app.solver.port import Diagnostic, ObjectiveTerms, SolveResult
from tests.db_fixtures import api_client, db_session, test_engine, toy_seeded  # noqa: F401
from tests.seed_loader import problem_from_seed_dir

TOY = Path(__file__).resolve().parents[2] / "seed" / "toy"
ON = date(2026, 8, 10)


def _trap(monkeypatch, target, name, message):
    def boom(*args, **kwargs):
        raise AssertionError(message)

    monkeypatch.setattr(target, name, boom)


# ---------------------------------------------------------------------------
# AppetenceScorer — consommé par prefilter et PulpMenuSolver
# ---------------------------------------------------------------------------

class FakeScorer:
    """Scorer factice : score constant, un seul segment plein tarif."""

    def score(self, recipe):
        return Decimal("1.000")

    def utility_segments(self, recipe):
        return [UtilitySegment(recipe.max_batch_servings, Decimal("1.000"))]


def test_appetence_scorer_is_substitutable(monkeypatch):
    _trap(
        monkeypatch, RuleBasedAppetenceScorer, "__init__",
        "RuleBasedAppetenceScorer atteint malgré l'injection d'un scorer factice",
    )
    problem = problem_from_seed_dir(TOY, ON)
    fake = FakeScorer()
    pre = prefilter_recipes(problem.recipes, problem.profile, fake)
    res = PulpMenuSolver(scorer_factory=lambda p: fake).solve(
        problem, pre, SolverConfig()
    )
    assert res.status == "Optimal"
    assert sum(res.servings_by_recipe.values()) >= 4


# ---------------------------------------------------------------------------
# MenuSolver — consommé par le service de plan (et donc l'API)
# ---------------------------------------------------------------------------

class FakeSolver:
    """Solveur factice : retourne un plan en conserve sans aucun MILP."""

    def solve(self, problem, prefiltered, config):
        servings = {"riz_nature": 4}
        terms = ObjectiveTerms(
            achats_cents=Decimal("180.00"),
            deplacements_cents=Decimal("0"), temps_cents=Decimal("0"),
            recuperation_cents=Decimal("0"), appetence_cents=Decimal("0"),
        )
        diag = Diagnostic(
            solver_status="Optimal", solve_time_s=0.0,
            mip_gap_requested=config.mip_gap, mip_gap_attained=None,
            objective_terms=terms, effective_params={},
            saturated_constraints={}, prefilter_counts=prefiltered.counts_by_stage,
            surplus_by_ingredient={}, distinct_recipes=1,
            distinct_dish_families=1,
            pantry_consumed_by_ingredient={},
            pantry_consumed_value_cents=Decimal("0.00"),
            max_share_of_demand=Decimal("1.0"),
            demand={"D_exact": "4.0", "borne_basse": "4", "borne_haute": "5"},
        )
        product = next(
            p for p in problem.products if p.external_key == "riz_400g"
        )
        store = problem.stores[0]
        from app.solver.port import PurchaseLine

        line = PurchaseLine(
            product_id=product.id, product_external_key=product.external_key,
            store_id=store.id, store_external_key=store.external_key,
            units=1, unit_price_cents_cad=180,
            taxed_total_cents_cad=Decimal("180.00"),
        )
        return SolveResult(
            status="Optimal", servings_by_recipe=servings,
            cooked_flags={"riz_nature": True}, purchases=(line,),
            stores_visited=(store.external_key,), surplus_by_ingredient={},
            diagnostic=diag,
        )


def test_menu_solver_is_substitutable_through_api(monkeypatch, api_client):
    """Le FakeSolver traverse POST /api/plan de bout en bout ; PuLP est piégé
    et ne doit jamais être atteint."""
    _trap(
        monkeypatch, PulpMenuSolver, "solve",
        "PulpMenuSolver atteint malgré l'injection d'un solveur factice",
    )
    from app.api.deps import get_solver
    from app.main import app

    app.dependency_overrides[get_solver] = lambda: FakeSolver()
    r = api_client.post("/api/plan", json={"config": {}, "on_date": str(ON)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["solver_status"] == "Optimal"
    assert body["menu"][0]["recipe_id"] == "riz_nature"
    assert body["grocery_list_by_store"][0]["lines"][0][
        "product_external_key"
    ] == "riz_400g"


# ---------------------------------------------------------------------------
# CircularPort et RecipeSourcePort — consommés par le pipeline de seeding
# ---------------------------------------------------------------------------

class FakeCircular:
    """Port de circulaire factice — le contrat du futur vrai scraper."""

    def fetch_week(self, store_id, week):
        from app.ports.dto import RawOfferDTO

        if (store_id, week) != ("toy_store", "2026-W33"):
            return []
        return [
            RawOfferDTO(
                store_external_key="toy_store", week="2026-W33",
                raw_text="FAKE — riz premium 1 kg",
                product_external_key="riz_1kg",
                price_cents_cad=299, regular_price_cents_cad=310,
                is_promo=True, valid_from="2026-08-10", valid_to="2026-08-16",
            )
        ]

    def all_weeks(self):
        return ["2026-W33"]

    def all_store_keys(self):
        return ["toy_store"]


class FakeRecipeSource:
    def load_all(self):
        from app.ports.dto import RecipeDTO, RecipeIngredientDTO

        return [
            RecipeDTO(
                id="fake_bol_riz", name="Bol de riz (source factice)",
                original_servings=2, prep_time_fixed_h=Decimal("0.1"),
                prep_time_marginal_h=Decimal("0.02"),
                min_batch_servings=1, max_batch_servings=6,
                ingredients=(
                    RecipeIngredientDTO(
                        canonical_ingredient_id="riz",
                        qty_fixed_per_batch_base_unit=Decimal("0"),
                        qty_marginal_per_serving_base_unit=Decimal("90"),
                    ),
                ),
            )
        ]


def test_ports_are_substitutable_in_seeding(monkeypatch, toy_seeded):
    """Les faux ports traversent le pipeline réel (staging → normalisation →
    market.price) ; les adaptateurs JSON sont piégés et ne doivent jamais
    être atteints."""
    import sqlalchemy

    from app.adapters.json_circular import JsonCircularAdapter
    from app.adapters.json_recipe_source import JsonRecipeSourceAdapter
    from app.seeding.seed import seed_catalog, seed_prices_via_ingestion

    _trap(monkeypatch, JsonCircularAdapter, "fetch_week",
          "JsonCircularAdapter atteint malgré l'injection d'un port factice")
    _trap(monkeypatch, JsonRecipeSourceAdapter, "load_all",
          "JsonRecipeSourceAdapter atteint malgré l'injection d'un port factice")

    with toy_seeded() as session:
        seed_catalog(session, TOY, recipe_source=FakeRecipeSource())
        seed_prices_via_ingestion(session, TOY, circular=FakeCircular())
        session.commit()

        assert session.execute(
            sqlalchemy.text("SELECT name FROM catalog.recipe WHERE id='fake_bol_riz'")
        ).scalar() == "Bol de riz (source factice)"
        row = session.execute(sqlalchemy.text(
            """SELECT pr.price_cents_cad, pr.is_promo
               FROM market.price pr JOIN market.product p ON p.id = pr.product_id
               WHERE p.external_key = 'riz_1kg'
                 AND pr.valid_from = '2026-08-10'"""
        )).one()
        assert (row.price_cents_cad, row.is_promo) == (299, True)
        assert session.execute(sqlalchemy.text(
            "SELECT count(*) FROM staging.raw_offer WHERE payload->>'raw_text' LIKE 'FAKE%'"
        )).scalar() == 1
        # Nettoyage de la recette factice pour les autres tests du module
        session.execute(sqlalchemy.text(
            "DELETE FROM catalog.recipe_ingredient WHERE recipe_id='fake_bol_riz'"))
        session.execute(sqlalchemy.text(
            "DELETE FROM catalog.recipe WHERE id='fake_bol_riz'"))
        session.commit()
