from decimal import Decimal

import pytest

from app.services.problem_data import PriceData, ProductData
from app.services.validation import (
    BatchBoundsError, CapacityError, DiversityInfeasibleError,
    EmptyProblemError, MissingPriceError, SalvageBoundError,
    UnitMismatchError, validate_problem,
)
from tests.conftest import (
    make_ingredient, make_problem, make_profile, make_recipe,
)


def big_recipes(n=6):
    return [make_recipe(rid=f"r{i}", beta=1, m=12) for i in range(n)]


def test_all_assertions_pass_and_bounds_returned():
    p = make_problem(recipes=big_recipes())
    passed, bounds = validate_problem(p, p.recipes)
    assert len(passed) == 7  # 1..6 + 6b
    assert (bounds.exact, bounds.low, bounds.high) == (Decimal("36.4"), 37, 41)


def test_assertion_1_salvage_bound_at_runtime_prices():
    # prix 300 c/kg → borne = 0,8·0,3 = 0,24 c/g ; σ = 0,25 doit lever
    p = make_problem(ingredients=[make_ingredient(sigma="0.25")],
                     recipes=big_recipes())
    with pytest.raises(SalvageBoundError):
        validate_problem(p, p.recipes)


def test_assertion_2_beta_zero():
    bad = [make_recipe(rid="bad", beta=0)] + big_recipes()
    p = make_problem(recipes=bad)
    with pytest.raises(BatchBoundsError):
        validate_problem(p, p.recipes)


def test_assertion_3_unit_mismatch():
    p = make_problem(
        ingredients=[make_ingredient(kind="mass", base_unit="ml")],
        recipes=big_recipes(),
    )
    with pytest.raises(UnitMismatchError):
        validate_problem(p, p.recipes)


def test_assertion_4_missing_price():
    p = make_problem(recipes=big_recipes(), prices=[])
    with pytest.raises(MissingPriceError):
        validate_problem(p, p.recipes)


def test_assertion_5_no_recipes_after_prefilter():
    p = make_problem(recipes=big_recipes())
    with pytest.raises(EmptyProblemError):
        validate_problem(p, ())


def test_assertion_6_tested_against_low_bound():
    # R_min·min β = 5×8 = 40 > ⌈36,4⌉ = 37 → infaisable, borne BASSE
    recipes = [make_recipe(rid=f"r{i}", beta=8, m=12) for i in range(6)]
    p = make_problem(profile=make_profile(r_min=5), recipes=recipes)
    with pytest.raises(DiversityInfeasibleError):
        validate_problem(p, p.recipes)


def test_assertion_6_alpha_check_is_ge_not_gt():
    """R_min = ⌈1/α⌉ exactement (4 = ⌈1/0,3⌉) doit PASSER : c'est un ≥."""
    p = make_problem(profile=make_profile(r_min=4, alpha="0.3"),
                     recipes=big_recipes())
    passed, _ = validate_problem(p, p.recipes)
    assert "6_compatibilite_diversite" in passed


def test_capacity_against_high_bound():
    # 5 recettes m=8, α=0,3 : cap/recette = min(⌊0,3·41⌋, 8) = 8 → 40 > 37 OK
    ok = [make_recipe(rid=f"r{i}", beta=1, m=8) for i in range(5)]
    p = make_problem(recipes=ok)
    validate_problem(p, p.recipes)
    # 4 recettes m=8 → capacité 32 < 37 → CapacityError
    p2 = make_problem(recipes=ok[:4])
    with pytest.raises(CapacityError):
        validate_problem(p2, p2.recipes)
