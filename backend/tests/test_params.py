from decimal import Decimal

from app.services.params import resolve_effective_params
from app.solver import SolverConfig
from tests.conftest import make_profile


def test_none_falls_back_to_profile_with_provenance():
    p = resolve_effective_params(make_profile(), SolverConfig())
    assert p.max_store_visits.value == 2
    assert p.max_store_visits.source == "profil"
    assert p.demand_slack_epsilon.value == Decimal("0.10")
    assert p.demand_slack_epsilon.source == "profil"


def test_overrides_win_with_provenance():
    cfg = SolverConfig(max_store_visits=1, max_share_per_recipe=0.5,
                       demand_slack_epsilon=0.0)
    p = resolve_effective_params(make_profile(), cfg)
    assert (p.max_store_visits.value, p.max_store_visits.source) == (1, "solver_config")
    assert p.max_share_per_recipe.value == Decimal("0.5")
    assert p.demand_slack_epsilon.value == Decimal("0.0")
    assert p.min_distinct_recipes.source == "profil"


def test_diagnostic_shape():
    d = resolve_effective_params(make_profile(), SolverConfig()).as_diagnostic()
    assert set(d) == {"max_store_visits", "min_distinct_recipes",
                      "max_share_per_recipe", "demand_slack_epsilon"}
    assert all({"valeur", "provenance"} == set(v) for v in d.values())
