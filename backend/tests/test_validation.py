import dataclasses
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.appetence import RuleBasedAppetenceScorer
from app.services.params import resolve_effective_params
from app.services.prefilter import prefilter_recipes
from app.services.validation import (
    BatchBoundsError, CapacityError, DiversityInfeasibleError,
    EmptyProblemError, MissingPriceError, SalvageBoundError,
    UnitMismatchError, validate_problem,
)
from app.solver.config import SolverConfig
from tests.conftest import (
    make_ingredient, make_problem, make_profile, make_recipe,
)
from tests.seed_loader import problem_from_seed_dir

SEED = Path(__file__).resolve().parents[2] / "seed"
ON = date(2026, 8, 10)


def big_recipes(n=6):
    return [make_recipe(rid=f"r{i}", beta=1, m=12) for i in range(n)]


def _params(problem, **overrides):
    """R_min/α/ε résolus (services/params.py::resolve_effective_params) —
    validate_problem doit toujours les recevoir déjà résolus, jamais relire
    problem.profile directement (voir sa docstring)."""
    return resolve_effective_params(problem.profile, SolverConfig(**overrides))


def test_all_assertions_pass_and_bounds_returned():
    p = make_problem(recipes=big_recipes())
    passed, bounds = validate_problem(p, p.recipes, _params(p))
    assert len(passed) == 7  # 1..6 + 6b
    assert (bounds.exact, bounds.low, bounds.high) == (Decimal("36.4"), 37, 41)


def test_assertion_1_salvage_bound_at_runtime_prices():
    # prix 300 c/kg → borne = 0,8·0,3 = 0,24 c/g ; σ = 0,25 doit lever
    p = make_problem(ingredients=[make_ingredient(sigma="0.25")],
                     recipes=big_recipes())
    with pytest.raises(SalvageBoundError):
        validate_problem(p, p.recipes, _params(p))


def test_assertion_2_beta_zero():
    bad = [make_recipe(rid="bad", beta=0)] + big_recipes()
    p = make_problem(recipes=bad)
    with pytest.raises(BatchBoundsError):
        validate_problem(p, p.recipes, _params(p))


def test_assertion_3_unit_mismatch():
    p = make_problem(
        ingredients=[make_ingredient(kind="mass", base_unit="ml")],
        recipes=big_recipes(),
    )
    with pytest.raises(UnitMismatchError):
        validate_problem(p, p.recipes, _params(p))


def test_assertion_4_missing_price():
    p = make_problem(recipes=big_recipes(), prices=[])
    with pytest.raises(MissingPriceError):
        validate_problem(p, p.recipes, _params(p))


def test_assertion_5_no_recipes_after_prefilter():
    p = make_problem(recipes=big_recipes())
    with pytest.raises(EmptyProblemError):
        validate_problem(p, (), _params(p))


def test_assertion_6_tested_against_low_bound():
    # R_min·min β = 5×8 = 40 > ⌈36,4⌉ = 37 → infaisable, borne BASSE
    recipes = [make_recipe(rid=f"r{i}", beta=8, m=12) for i in range(6)]
    p = make_problem(profile=make_profile(r_min=5), recipes=recipes)
    with pytest.raises(DiversityInfeasibleError):
        validate_problem(p, p.recipes, _params(p))


def test_assertion_6_alpha_check_is_ge_not_gt():
    """R_min = ⌈1/α⌉ exactement (4 = ⌈1/0,3⌉) doit PASSER : c'est un ≥."""
    p = make_problem(profile=make_profile(r_min=4, alpha="0.3"),
                     recipes=big_recipes())
    passed, _ = validate_problem(p, p.recipes, _params(p))
    assert "6_compatibilite_diversite" in passed


def test_capacity_against_high_bound():
    # 5 recettes m=8, α=0,3 : cap/recette = min(⌊0,3·41⌋, 8) = 8 → 40 > 37 OK
    ok = [make_recipe(rid=f"r{i}", beta=1, m=8) for i in range(5)]
    p = make_problem(recipes=ok)
    validate_problem(p, p.recipes, _params(p))
    # 4 recettes m=8 → capacité 32 < 37 → CapacityError
    p2 = make_problem(recipes=ok[:4])
    with pytest.raises(CapacityError):
        validate_problem(p2, p2.recipes, _params(p2))


# ---------------------------------------------------------------------------
# validate_problem doit lire R_min/α/ε résolus (params), jamais
# problem.profile directement — sinon une surcharge SolverConfig est
# honorée par le solveur mais ignorée par la validation pré-solveur, qui
# vérifie alors des bornes différentes de celles réellement construites.
# ---------------------------------------------------------------------------

def test_assertion_6_respects_min_distinct_recipes_override():
    """1 seule famille disponible : échoue avec R_min=4 du profil, doit
    passer avec une surcharge SolverConfig à R_min=1. α=1,0 et m=50
    neutralisent le contrôle R_min ≥ ⌈1/α⌉ et la capacité entière
    (assertions 6 second volet et 6b) pour isoler uniquement le contrôle
    sur le nombre de familles ici testé."""
    p = make_problem(
        profile=make_profile(r_min=4, alpha="1.0"),
        recipes=[make_recipe(rid="r0", beta=1, m=50)],
    )
    with pytest.raises(DiversityInfeasibleError):
        validate_problem(p, p.recipes, _params(p))

    passed, _ = validate_problem(
        p, p.recipes, _params(p, min_distinct_recipes=1)
    )
    assert "6_compatibilite_diversite" in passed


def test_assertion_6_respects_max_share_per_recipe_override():
    """α=0,2 du profil exige R_min ≥ ⌈1/0,2⌉=5 : R_min=4 échoue. Une
    surcharge SolverConfig à α=0,3 (⌈1/0,3⌉=4) doit faire passer le même
    problème sans toucher au profil."""
    p = make_problem(
        profile=make_profile(r_min=4, alpha="0.2"), recipes=big_recipes(n=6)
    )
    with pytest.raises(DiversityInfeasibleError):
        validate_problem(p, p.recipes, _params(p))

    passed, _ = validate_problem(
        p, p.recipes, _params(p, max_share_per_recipe=0.3)
    )
    assert "6_compatibilite_diversite" in passed


def test_bounds_returned_reflect_resolved_epsilon_not_raw_profile():
    """Les bornes de demande retournées (et réutilisées telles quelles par
    solve(), plutôt que recalculées) doivent venir de l'ε résolu — sinon
    elles divergent silencieusement de celles que le solveur construit
    réellement dans le modèle."""
    p = make_problem(profile=make_profile(epsilon="0.10"), recipes=big_recipes())
    _, bounds_profile = validate_problem(p, p.recipes, _params(p))
    assert bounds_profile.epsilon == Decimal("0.10")

    _, bounds_override = validate_problem(
        p, p.recipes, _params(p, demand_slack_epsilon=0.5)
    )
    assert bounds_override.epsilon == Decimal("0.5")
    assert bounds_override.high > bounds_profile.high


# ---------------------------------------------------------------------------
# D17 (docs/deviations.md) : assertions 6/6b dédupliquées par dish_family_id
# ---------------------------------------------------------------------------

def test_assertion_6_old_formula_missed_a_family_bias():
    """L'ancienne formule R_min·min(β) sur le minimum GLOBAL passait à tort
    dès qu'une seule famille détenait ce minimum : ici min global = 1 (plat
    "petit"), R_min=4 → 4×1=4 ≤ 37 aurait laissé passer. Mais les 3 AUTRES
    plats distincts nécessaires ont chacun β=20 : la vraie somme minimale
    est 1+20+20+20=61 > 37 — bien infaisable, et l'assertion doit le voir."""
    recipes = [
        make_recipe(rid="petit", beta=1, m=12, dish_family_id="petit"),
        make_recipe(rid="petit_familial", beta=8, m=16, dish_family_id="petit"),
        make_recipe(rid="gros_a", beta=20, m=25, dish_family_id="gros_a"),
        make_recipe(rid="gros_b", beta=20, m=25, dish_family_id="gros_b"),
        make_recipe(rid="gros_c", beta=20, m=25, dish_family_id="gros_c"),
    ]
    p = make_problem(profile=make_profile(r_min=4), recipes=recipes)
    with pytest.raises(DiversityInfeasibleError):
        validate_problem(p, p.recipes, _params(p))


def test_assertion_6_family_counted_once_with_its_smallest_beta():
    """Une famille à 2 variantes ne compte qu'UNE fois, avec son β le plus
    favorable (le plus petit) — ni doublée, ni prise au pire des deux."""
    recipes = [
        make_recipe(rid="plat_a", beta=2, m=12, dish_family_id="plat_a"),
        make_recipe(rid="plat_a_familial", beta=4, m=16, dish_family_id="plat_a"),
        make_recipe(rid="plat_b", beta=2, m=12, dish_family_id="plat_b"),
        make_recipe(rid="plat_c", beta=2, m=12, dish_family_id="plat_c"),
        make_recipe(rid="plat_d", beta=2, m=12, dish_family_id="plat_d"),
    ]
    p = make_problem(profile=make_profile(r_min=4), recipes=recipes)
    passed, _ = validate_problem(p, p.recipes, _params(p))
    assert "6_compatibilite_diversite" in passed


def test_assertion_6_fewer_families_than_r_min_raises():
    """R_min=4 mais seulement 3 familles distinctes (6 recettes, 2 variantes
    chacune) : infaisable quels que soient les β — depuis D16 une famille ne
    peut jamais fournir plus d'un plat distinct."""
    recipes = [
        make_recipe(rid="a", beta=1, m=12, dish_family_id="a"),
        make_recipe(rid="a_familial", beta=1, m=12, dish_family_id="a"),
        make_recipe(rid="b", beta=1, m=12, dish_family_id="b"),
        make_recipe(rid="b_familial", beta=1, m=12, dish_family_id="b"),
        make_recipe(rid="c", beta=1, m=12, dish_family_id="c"),
        make_recipe(rid="c_familial", beta=1, m=12, dish_family_id="c"),
    ]
    p = make_problem(profile=make_profile(r_min=4), recipes=recipes)
    with pytest.raises(DiversityInfeasibleError):
        validate_problem(p, p.recipes, _params(p))


def test_capacity_6b_does_not_double_count_family_variants():
    """6b (miroir de 6) : une famille à 2 variantes de capacité 8 chacune ne
    doit apporter que 8 à la capacité totale, pas 16 — une seule variante
    peut être active à la fois (D16)."""
    recipes = [
        make_recipe(rid="plat_a", beta=1, m=8, dish_family_id="plat_a"),
        make_recipe(rid="plat_a_familial", beta=1, m=8, dish_family_id="plat_a"),
        make_recipe(rid="plat_b", beta=1, m=8, dish_family_id="plat_b"),
        make_recipe(rid="plat_c", beta=1, m=8, dish_family_id="plat_c"),
        make_recipe(rid="plat_d", beta=1, m=8, dish_family_id="plat_d"),
    ]
    # Capacité correcte (1 valeur/famille) = 4×8 = 32 < 37 → CapacityError.
    # L'ancien calcul (1 valeur/recette) aurait donné 5×8 = 40 ≥ 37 (passe à
    # tort, "plat_a" compté deux fois pour une seule famille disponible).
    p = make_problem(profile=make_profile(r_min=4), recipes=recipes)
    with pytest.raises(CapacityError):
        validate_problem(p, p.recipes, _params(p))


def test_assertion_6_catches_n_repas_2_on_seed_profile_before_solver():
    """Avant le correctif, n_repas=2 sur le profil du seed principal passait
    toutes les assertions puis échouait au solveur (Infeasible) sans message
    exploitable (repéré en balayant n_repas de 2 à 14). Avec la
    déduplication par famille, l'assertion 6 l'attrape directement, avec un
    message lisible."""
    problem = problem_from_seed_dir(SEED / "main", ON)
    profile = dataclasses.replace(problem.profile, meals_per_horizon=2)
    problem = dataclasses.replace(problem, profile=profile)
    pre = prefilter_recipes(
        problem.recipes, problem.profile, RuleBasedAppetenceScorer(problem)
    )
    with pytest.raises(DiversityInfeasibleError) as exc_info:
        validate_problem(problem, pre.surviving, _params(problem))
    msg = str(exc_info.value)
    assert "R_min" in msg or "famille" in msg
