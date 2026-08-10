"""D16 (docs/deviations.md) : exclusion mutuelle des variantes d'échelle du
même plat — sans elle, deux recettes partageant un dish_family_id peuvent
être cuisinées ensemble, chacune sous le plafond de part x_r ≤ α·D
individuellement, leur somme ne l'étant pas ; et le compte Σδ_r ≥ R_min se
gonfle sans varier réellement le menu.

Instance délibérément minuscule : 2 "variantes" du même plat (même
dish_family_id, économies d'échelle non modélisées ici — seul le lien de
famille compte), D = 4 → bornes [4, 5], une seule recette a assez de
capacité (m=8) pour couvrir la demande à elle seule.
"""

from app.services.appetence import RuleBasedAppetenceScorer
from app.services.prefilter import prefilter_recipes
from app.solver import PulpMenuSolver, SolverConfig
from tests.conftest import make_problem, make_profile, make_recipe


def _solve(config, r_min, alpha):
    base = make_recipe(rid="soupe", beta=1, m=8, dish_family_id="soupe")
    familial = make_recipe(
        rid="soupe_familial", beta=1, m=8, dish_family_id="soupe"
    )
    profile = make_profile(
        rho=("1.0",), meals=4, epsilon="0.10", r_min=r_min, alpha=alpha
    )
    problem = make_problem(profile=profile, recipes=[base, familial])
    pre = prefilter_recipes(
        problem.recipes, problem.profile, RuleBasedAppetenceScorer(problem)
    )
    return PulpMenuSolver().solve(problem, pre, config)


def test_variant_exclusion_forbids_two_variants_together():
    """R_min = 2 sur une famille à 2 variantes est arithmétiquement
    infaisable dès lors que l'exclusion mutuelle est active : on ne peut pas
    tirer deux "recettes distinctes" d'une seule famille. La preuve que la
    contrainte contraint réellement, pas qu'elle est décorative."""
    cfg = SolverConfig(enable_diversity=True, enable_variant_exclusion=True)
    res = _solve(cfg, r_min=2, alpha="0.9")
    assert res.status != "Optimal"


def test_disabling_variant_exclusion_restores_old_bypass():
    """Sans le drapeau, les deux variantes PEUVENT satisfaire R_min = 2 à
    elles seules — exactement le contournement documenté en D16."""
    cfg = SolverConfig(enable_diversity=True, enable_variant_exclusion=False)
    res = _solve(cfg, r_min=2, alpha="0.9")
    assert res.status == "Optimal"
    assert len(res.servings_by_recipe) == 2
    assert res.diagnostic.distinct_dish_families == 1  # un seul plat, malgré 2 recettes


def test_variant_exclusion_caps_delta_sum_when_family_not_required():
    """Cas normal (R_min = 1, une seule variante suffit) : l'exclusion ne
    rend rien infaisable, mais au plus une variante est retenue et
    distinct_dish_families == distinct_recipes."""
    cfg = SolverConfig(enable_diversity=True, enable_variant_exclusion=True)
    res = _solve(cfg, r_min=1, alpha="1.0")
    assert res.status == "Optimal"
    assert len(res.servings_by_recipe) == 1
    assert res.diagnostic.distinct_dish_families == 1
    assert res.diagnostic.distinct_recipes == 1
