"""Plancher de dépense d'épicerie : « emploie mon budget », en dollars.

Le plancher d'appétence répond « quel menu », pas « quel montant ». Mesuré sur
le catalogue de `seed/main` et le marché de `seed/demo` (D34) à la semaine du
13 août 2026 : U_min = 50 → panier de 32,07 $,
U_min = 70 → 62,77 $, U_min = 90 → infaisable. Un ménage qui veut employer son
budget raisonne en dollars, et la correspondance points → dollars change à
chaque circulaire.

Le piège que ces tests gardent : un plancher de dépense n'améliore le menu que
si quelque chose récompense un menu meilleur. L'appétence en crédit dans
l'objectif joue ce rôle — parmi tous les paniers atteignant le montant, le
solveur retient le plus appétissant. En mode « constraint », l'appétence quitte
l'objectif : plus rien ne départage, et le chemin le moins cher vers le montant
devient le surplus. Le ménage paierait son budget en gaspillage.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.appetence import RuleBasedAppetenceScorer
from app.services.params import CONFIG, PROFILE, resolve_effective_params
from app.services.prefilter import prefilter_recipes
from app.services.validation import (
    SpendFloorWithoutRewardError,
    min_taxed_price_per_base_unit,
    validate_problem,
)
from app.solver.config import SolverConfig
from app.solver.model import PulpMenuSolver
from tests.conftest import make_profile
from tests.seed_loader import problem_from_seed_dir

from pathlib import Path

SEED = Path(__file__).resolve().parents[2] / "seed"
ON = date(2026, 8, 14)


def _solve(**config):
    problem = problem_from_seed_dir(SEED / "main", ON, market_dir=SEED / "demo")
    pre = prefilter_recipes(
        problem.recipes,
        problem.profile,
        RuleBasedAppetenceScorer(problem),
        frozenset(min_taxed_price_per_base_unit(problem)),
    )
    # `enable_batch_fixed_cost` est éteint explicitement : ce fichier mesure le
    # plancher de dépense, un mécanisme à la fois (README, « Activer les
    # mécanismes du solveur un à un »). Depuis D38 le drapeau est allumé par
    # défaut, et le laisser entrer ici déplaçait les chiffres mesurés du
    # plancher sans rien dire du plancher lui-même.
    cfg = SolverConfig(
        solver_time_limit_s=120,
        mip_gap=0.01,
        enable_batch_fixed_cost=False,
        **config,
    )
    return PulpMenuSolver().solve(problem, pre, cfg)


def test_the_profile_supplies_the_floor_and_the_config_overrides_it():
    import dataclasses

    profil = dataclasses.replace(
        make_profile(), min_grocery_spend_cents_cad=6000
    )

    depuis_profil = resolve_effective_params(profil, SolverConfig())
    assert depuis_profil.min_grocery_spend_cents_cad.value == 6000
    assert depuis_profil.min_grocery_spend_cents_cad.source == PROFILE

    surcharge = resolve_effective_params(
        profil, SolverConfig(min_grocery_spend_cents_cad=9000)
    )
    assert surcharge.min_grocery_spend_cents_cad.value == 9000
    assert surcharge.min_grocery_spend_cents_cad.source == CONFIG


def test_the_floor_appears_in_the_diagnostic_with_its_provenance():
    d = resolve_effective_params(
        make_profile(), SolverConfig(min_grocery_spend_cents_cad=6000)
    ).as_diagnostic()
    assert d["min_grocery_spend_cents_cad"] == {
        "valeur": "6000",
        "provenance": CONFIG,
    }


def test_without_a_floor_the_basket_stays_below_it():
    """Le point de départ : c'est bien le plancher qui change le panier, pas
    autre chose dans la configuration."""
    sans = _solve(appetence_mode="objective")
    assert sans.status == "Optimal"
    assert sans.diagnostic.objective_terms.achats_cents < 6000


#: Le plancher est imposé sur l'expression PuLP, en flottants ; le montant
#: rapporté est recalculé en `Decimal` depuis la solution entière (INVARIANTS :
#: « les flottants de PuLP ne servent qu'à la résolution »). Les deux peuvent
#: donc diverger de moins d'un cent — mesuré : 5 999,42 contre un plancher de
#: 6 000 sur le catalogue Super C réel. Tolérer un cent est exact ; affirmer
#: l'égalité stricte serait faux.
_TOLERANCE_CENTS = Decimal("1")


def test_the_floor_is_reached_and_the_money_buys_food_not_surplus():
    avec = _solve(appetence_mode="objective", min_grocery_spend_cents_cad=6000)
    assert avec.status == "Optimal"
    achats = avec.diagnostic.objective_terms.achats_cents
    assert achats >= 6000 - _TOLERANCE_CENTS

    # Le montage tient debout seulement si l'argent va dans l'assiette. Le
    # surplus est mesuré par le solveur lui-même : `surplus_by_ingredient`.
    # Sans cette garde, un plancher « satisfait » pourrait n'être que du
    # gaspillage facturé au ménage.
    sans = _solve(appetence_mode="objective")
    assert (
        avec.diagnostic.objective_terms.appetence_cents
        >= sans.diagnostic.objective_terms.appetence_cents
    )


def test_an_absurd_floor_stops_buying_appetence_and_only_buys_quantity():
    """La limite réelle du mécanisme, mesurée plutôt que supposée.

    J'attendais qu'un plancher démesuré soit infaisable. Il ne l'est pas : rien
    ne borne la quantité achetée par le haut (la couverture est
    approvisionnement ≥ besoin), donc le solveur atteint n'importe quel montant
    en achetant plus. Ce qui sature, c'est l'appétence — et c'est ça qu'il faut
    tenir, parce que c'est la frontière entre « employer son budget » et
    « acheter du gaspillage ».

    Mesuré sur le catalogue de `seed/main` et le marché de `seed/demo`
    (D34), semaine du 13 août 2026, part de la quantité
    achetée qui n'est pas consommée par le menu : 19,4 % sans plancher (les
    formats d'emballage, incompressible), 28,6 % à 60 $, 32,2 % à 90 $, 69,0 %
    à 200 $, 88,8 % à 600 $. L'appétence, elle, passe de 54,50 à 67,30 puis
    71,40 et n'augmente plus.
    """
    raisonnable = _solve(
        appetence_mode="objective", min_grocery_spend_cents_cad=9000
    )
    absurde = _solve(
        appetence_mode="objective", min_grocery_spend_cents_cad=60_000
    )
    assert raisonnable.status == absurde.status == "Optimal"
    assert absurde.diagnostic.objective_terms.achats_cents >= 60_000 - _TOLERANCE_CENTS

    # Sept fois le montant n'achète pas plus d'appétence : tout le supplément
    # part en quantité. Un plancher n'est un budget que dans sa plage utile.
    assert (
        absurde.diagnostic.objective_terms.appetence_cents
        <= raisonnable.diagnostic.objective_terms.appetence_cents * Decimal("1.01")
    )


def test_the_floor_is_refused_when_appetence_leaves_the_objective():
    """La garde centrale : plancher + mode « constraint » achèterait du
    surplus. Refusé avant le solveur, avec la cause nommée."""
    problem = problem_from_seed_dir(SEED / "main", ON, market_dir=SEED / "demo")
    params = resolve_effective_params(
        problem.profile,
        SolverConfig(
            appetence_u_min_dollars=50, min_grocery_spend_cents_cad=6000
        ),
    )
    assert params.appetence_mode == "constraint"

    with pytest.raises(SpendFloorWithoutRewardError) as erreur:
        validate_problem(problem, problem.recipes, params)
    message = str(erreur.value)
    assert "6000" in message
    assert "surplus" in message


def test_the_floor_constrains_the_same_expression_the_objective_minimises():
    """`enable_staples` biaise le prix vu par le solveur. Le plancher doit
    porter sur cette même expression, sinon les deux se croient d'accord en
    divergeant : le plancher se dirait atteint dans une métrique que l'objectif
    ne minimise pas."""
    res = _solve(
        appetence_mode="objective",
        enable_staples=True,
        min_grocery_spend_cents_cad=6000,
    )
    assert res.status == "Optimal"
    assert res.diagnostic.objective_terms.achats_cents >= 6000 - _TOLERANCE_CENTS
