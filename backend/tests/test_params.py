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
    """U_min a rejoint les paramètres surchargeables du profil.

    Les deux clés ajoutées le sont volontairement : `appetence_u_min_dollars`
    est le plancher retenu avec sa provenance, `appetence_mode` le mode qui
    s'en dérive. Ce dernier porte la provenance « dérivé » — il n'est lu ni
    sur le profil ni sur la configuration, il se calcule.
    """
    d = resolve_effective_params(make_profile(), SolverConfig()).as_diagnostic()
    assert set(d) == {"max_store_visits", "min_distinct_recipes",
                      "max_share_per_recipe", "demand_slack_epsilon",
                      "appetence_u_min_dollars",
                      "appetence_mode"}
    assert all({"valeur", "provenance"} == set(v) for v in d.values())
    assert d["appetence_mode"]["provenance"] == "dérivé"


def test_profile_floor_drives_the_appetence_mode():
    """Le plancher persisté suffit — aucun mode à réarmer à chaque plan.

    C'est tout l'objet du déplacement de ce réglage vers les préférences :
    avant, le mode vivait dans l'état d'un onglet développeur et repartait au
    défaut à chaque rafraîchissement, ce qui rendait le plancher inopérant.
    """
    sans = resolve_effective_params(make_profile(), SolverConfig())
    assert sans.appetence_u_min_dollars.value is None
    assert sans.appetence_mode == "objective"

    avec = resolve_effective_params(
        make_profile(appetence_u_min_dollars=Decimal("65")), SolverConfig()
    )
    assert avec.appetence_u_min_dollars.value == Decimal("65")
    assert avec.appetence_u_min_dollars.source == "profil"
    assert avec.appetence_mode == "constraint"


def test_solver_config_overrides_the_profile_floor_both_ways():
    """Le mode développeur garde la main, dans les deux sens."""
    profile = make_profile(appetence_u_min_dollars=Decimal("65"))

    remplace = resolve_effective_params(
        profile, SolverConfig(appetence_mode="constraint", appetence_u_min_dollars=80)
    )
    assert remplace.appetence_u_min_dollars.value == Decimal("80")
    assert remplace.appetence_u_min_dollars.source == "solver_config"

    # « objective » demandé explicitement écarte le plancher du profil, sinon
    # il n'y aurait plus aucun moyen de revenir au crédit dans l'objectif.
    ecarte = resolve_effective_params(profile, SolverConfig(appetence_mode="objective"))
    assert ecarte.appetence_u_min_dollars.value is None
    assert ecarte.appetence_u_min_dollars.source == "solver_config"
    assert ecarte.appetence_mode == "objective"
