"""Chaque drapeau doit produire un modèle valide et résoluble SEUL — et le jeu
de seed principal doit se résoudre avec tout activé. Les recettes importées
sans produit tarifé sont éliminées par le même préfiltre que la production."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.appetence import RuleBasedAppetenceScorer
from app.services.prefilter import prefilter_recipes
from app.services.validation import min_taxed_price_per_base_unit
from app.solver import PulpMenuSolver, SolverConfig
from tests.seed_loader import problem_from_seed_dir

SEED = Path(__file__).resolve().parents[2] / "seed"
ON = date(2026, 8, 10)

FLAGS = ["enable_multi_store", "enable_batch_fixed_cost", "enable_salvage",
         "enable_perishable_penalty", "enable_time_cost", "enable_staples",
         "enable_diversity"]


@pytest.fixture(scope="module")
def toy():
    p = problem_from_seed_dir(SEED / "toy", ON)
    return p, prefilter_recipes(p.recipes, p.profile, RuleBasedAppetenceScorer(p))


@pytest.mark.parametrize("flag", FLAGS)
def test_each_flag_alone_is_solvable(toy, flag):
    problem, pre = toy
    res = PulpMenuSolver().solve(problem, pre, SolverConfig(**{flag: True}))
    assert res.status == "Optimal"
    total = sum(res.servings_by_recipe.values())
    assert 4 <= total <= 5  # bornes de demande du jouet


def test_main_seed_all_flags_on():
    """Intégration : le catalogue principal sur le marché de démonstration
    (D34), tous mécanismes actifs. D = 36,4 → Σx ∈ [37, 41] ; K = 2 arrêts ;
    R_min = 4 ; α = 0,3."""
    problem = problem_from_seed_dir(SEED / "main", ON, market_dir=SEED / "demo")
    pre = prefilter_recipes(
        problem.recipes,
        problem.profile,
        RuleBasedAppetenceScorer(problem),
        frozenset(min_taxed_price_per_base_unit(problem)),
    )
    cfg = SolverConfig(
        enable_multi_store=True, enable_batch_fixed_cost=True,
        enable_salvage=True, enable_perishable_penalty=True,
        enable_time_cost=True, enable_staples=True,
        enable_diversity=True, solver_time_limit_s=120, mip_gap=0.01,
    )
    res = PulpMenuSolver().solve(problem, pre, cfg)
    assert res.status == "Optimal"

    total = sum(res.servings_by_recipe.values())
    assert 37 <= total <= 41
    assert len(res.servings_by_recipe) >= 4                       # R_min
    cap = Decimal("0.3") * 41
    assert all(x <= cap for x in res.servings_by_recipe.values())  # α·D_high
    assert 1 <= len(res.stores_visited) <= 2                       # K
    assert res.purchases                                           # on achète
    d = res.diagnostic
    assert d.objective_terms.total_cents() != 0
    # L'import Cook ajoute une recette entièrement couverte par le catalogue
    # tarifé; elle rejoint donc les candidates avant la limite du préfiltre.
    assert d.prefilter_counts["troncature"] == 41
    # Sept, et non huit : l'assertion 0 (cohérence plancher de dépense ×
    # mode d'appétence) est partie avec le plancher lui-même (D40).
    assert len(d.assertions_passed) == 8  # 1..6 + 6b + 6c
    # Les portions produites sont couvertes par les achats :
    # les couvertures saturées listées existent bien dans le problème.
    for iid in d.saturated_constraints["couvertures_ingredients"]:
        assert iid in problem.ingredients
    # D16 : exclusion mutuelle des variantes d'échelle — deux recettes du
    # même plat (ex. chili_lentilles / chili_lentilles_familial) ne doivent
    # plus jamais être retenues ensemble, et le compte de familles distinctes
    # doit coïncider avec le compte de recettes distinctes.
    families_by_recipe = {r.id: r.dish_family_id for r in problem.recipes}
    selected_families = [
        families_by_recipe[rid] for rid in res.servings_by_recipe
    ]
    assert len(selected_families) == len(set(selected_families)), (
        "deux variantes du même plat retenues ensemble"
    )
    assert d.distinct_dish_families == len(res.servings_by_recipe)
