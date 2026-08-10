"""D16 (docs/deviations.md) : exclusion mutuelle des variantes d'échelle du
même plat — sans elle, deux recettes partageant un dish_family_id peuvent
être cuisinées ensemble, chacune sous le plafond de part x_r ≤ α·D
individuellement, leur somme ne l'étant pas ; et le compte Σδ_r ≥ R_min se
gonfle sans varier réellement le menu.

Instance délibérément minuscule : 2 "variantes" du même plat (même
dish_family_id, économies d'échelle non modélisées ici — seul le lien de
famille compte), D = 4 → bornes [4, 5], une seule recette a assez de
capacité (m=8) pour couvrir la demande à elle seule.

D17 (docs/deviations.md) : les scénarios ci-dessous forçaient auparavant la
combinaison via R_min = 2 sur une famille à une seule paire de variantes —
depuis le correctif de l'assertion 6 (déduplication par dish_family_id),
ce cas précis est désormais rejeté AVANT le solveur (voir
tests/test_validation.py::test_assertion_6_fewer_families_than_r_min_raises),
ce qui est le comportement voulu : une infaisabilité arithmétique doit être
détectée explicitement, pas découverte via un statut "Infeasible" opaque du
solveur. Les tests ci-dessous démontrent donc le mécanisme RÉEL du
contournement — pas une infaisabilité forcée par R_min, mais un CHOIX
économique : sans exclusion, scinder la demande entre les deux variantes
récolte deux fois le premier segment (plein tarif) de la lassitude concave
de l'appétence, ce qui est strictement plus avantageux que de tout mettre
sur une seule variante. R_min = 1 ici : rien n'oblige à utiliser les deux
variantes, seule l'économie d'appétence y pousse le solveur.
"""

from app.services.appetence import RuleBasedAppetenceScorer
from app.services.prefilter import prefilter_recipes
from app.solver import PulpMenuSolver, SolverConfig
from tests.conftest import make_problem, make_profile, make_recipe


def _solve(config, r_min, alpha, m=8):
    base = make_recipe(rid="soupe", beta=1, m=m, dish_family_id="soupe")
    familial = make_recipe(
        rid="soupe_familial", beta=1, m=m, dish_family_id="soupe"
    )
    profile = make_profile(
        rho=("1.0",), meals=4, epsilon="0.10", r_min=r_min, alpha=alpha
    )
    problem = make_problem(profile=profile, recipes=[base, familial])
    pre = prefilter_recipes(
        problem.recipes, problem.profile, RuleBasedAppetenceScorer(problem)
    )
    return PulpMenuSolver().solve(problem, pre, config)


def test_disabling_variant_exclusion_lets_solver_split_for_appetence():
    """Sans exclusion, le solveur scinde la demande (2+2) entre les deux
    variantes de la même famille : chacune reste dans son premier segment
    (plein tarif), pour 4u d'appétence au lieu de 3,3u en tout mettant sur
    une seule (2 portions au plein tarif + 2 au tarif dégressif). C'est
    exactement le contournement documenté en D16 — un choix économique, pas
    une contrainte forcée par R_min (ici R_min = 1)."""
    cfg = SolverConfig(enable_diversity=True, enable_variant_exclusion=False)
    res = _solve(cfg, r_min=1, alpha="1.0")
    assert res.status == "Optimal"
    assert len(res.servings_by_recipe) == 2
    assert set(res.servings_by_recipe) == {"soupe", "soupe_familial"}
    assert res.diagnostic.distinct_recipes == 2
    assert res.diagnostic.distinct_dish_families == 1  # un seul plat, malgré 2 recettes


def test_variant_exclusion_forces_single_variant_and_costs_appetence():
    """Avec exclusion (défaut), une seule variante peut être active : toute
    la demande retombe sur elle, entamant son 2e segment (tarif dégressif).
    Le menu reste optimal (rien n'est infaisable, contrairement au cas
    R_min forcé) mais l'appétence récoltée est strictement moindre que sans
    exclusion — le contournement a un coût mesurable, pas seulement
    théorique (comparer avec le test précédent)."""
    cfg = SolverConfig(enable_diversity=True, enable_variant_exclusion=True)
    res = _solve(cfg, r_min=1, alpha="1.0")
    assert res.status == "Optimal"
    assert len(res.servings_by_recipe) == 1
    assert res.diagnostic.distinct_recipes == 1
    assert res.diagnostic.distinct_dish_families == 1

    without = _solve(
        SolverConfig(enable_diversity=True, enable_variant_exclusion=False),
        r_min=1, alpha="1.0",
    )
    assert (
        without.diagnostic.objective_terms.appetence_cents
        > res.diagnostic.objective_terms.appetence_cents
    )
