"""Tests du solveur sur l'instance jouet — optima calculés À LA MAIN.

Instance (seed/toy) : 1 magasin, 3 recettes, 4 produits, ε = 0,10 :
D = 4·1,0 = 4 → bornes [4, ⌈4,4⌉ = 5].

Données : riz_nature (80 g riz/portion, τf 0,1, τm 0,02, m 8) ; dahl_toy
(70 g lentille + 40 g riz/portion, τf 0,2, τm 0,03, m 8) ; omelette_toy
(2 œufs/portion, m 4). Prix : riz 1 kg = 300 c, riz 400 g = 180 c,
lentille 500 g = 250 c, œufs ×12 = 450 c. Aucun tag → u_r = 1,30 $ pour tout.

Segments concaves : m = 8 → 2 portions à 130 c, 3 à 84,5 c, 3 à 45,5 c ;
m = 4 → 1 à 130 c, 1 à 84,5 c, 2 à 45,5 c.

=== Calcul manuel 1 — configuration de développement (tout à False) ===
Objectif = achats − appétence. Candidats (dominants) :
- x_riz = 5 : besoin 400 g → 1× riz_400g = 180 c ;
  utilité = 2·130 + 3·84,5 = 513,5 c → objectif = −333,5 c.   ← OPTIMUM
- x_riz = 4 : 320 g → 180 c ; utilité 2·130 + 2·84,5 = 429 → −249.
- x_riz = 5 via riz_1kg : 300 − 513,5 = −213,5.
- riz 2 + dahl 3 (ou riz 3 + dahl 2) : riz 280 g → 180 c, lentille → 250 c ;
  utilité 604,5 → −174,5. L'ajout du dahl coûte 250 c pour 344,5 c bruts,
  moins bon que les portions marginales de riz.
- Toute variante avec omelette paie 450 c pour ≤ 130 c d'utilité utile.
Menu MONOTONE attendu : c'est la démonstration que la diversité est nécessaire.

=== Calcul manuel 2 — diversité activée (R_min = 2, α = 0,75) ===
x_r ≤ 0,75·5 = 3,75 → x_r ≤ 3 (entier). Meilleurs candidats :
- riz 3 + dahl 2 (ou riz 2 + dahl 3) : achats 430 c, utilité 604,5 c
  → objectif = −174,5 c.   ← OPTIMUM (optima multiples, même valeur)
- riz 3 + dahl 1 : achats 430, utilité 474,5 → −44,5.
- riz 3 + omelette 1 : achats 630, utilité 474,5 → +155,5.

=== Calcul manuel 3 — lot fixe + coût du temps (diversité off) ===
κ = 1500 c/h ; temps = τf·δ + τm·x.
- x_riz = 5 : 180 + 1500·(0,1 + 0,02·5) − 513,5 = 180 + 300 − 513,5
  = −33,5 c.   ← OPTIMUM
- x_riz = 4 : 180 + 1500·0,18 − 429 = +21 (la 5e portion vaut 84,5 c pour
  30 c de temps marginal).
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.appetence import RuleBasedAppetenceScorer
from app.services.prefilter import prefilter_recipes
from app.solver import PulpMenuSolver, SolverConfig
from tests.seed_loader import problem_from_seed_dir

TOY = Path(__file__).resolve().parents[2] / "seed" / "toy"
ON = date(2026, 8, 10)


@pytest.fixture(scope="module")
def toy():
    problem = problem_from_seed_dir(TOY, ON)
    pre = prefilter_recipes(
        problem.recipes, problem.profile, RuleBasedAppetenceScorer(problem)
    )
    return problem, pre


def solve(toy, **kwargs):
    problem, pre = toy
    return PulpMenuSolver().solve(problem, pre, SolverConfig(**kwargs))


def objective_cents(result) -> Decimal:
    return result.diagnostic.objective_terms.total_cents()


def test_pantry_value_zero_when_pantry_disabled(toy):
    """Sans enable_pantry_stock, aucun stock n'entre dans le modèle : la
    valeur consommée est nulle même si le garde-manger est garni."""
    res = solve(toy)
    assert res.diagnostic.pantry_consumed_value_cents == Decimal("0.00")
    assert res.diagnostic.pantry_consumed_by_ingredient == {}


def test_default_config_optimum_and_monotone_menu(toy):
    """Calcul manuel 1 : optimum −333,5 c, menu monotone ATTENDU sans
    diversité (spec : ce n'est pas un bug)."""
    res = solve(toy)
    assert res.status == "Optimal"
    assert res.servings_by_recipe == {"riz_nature": 5}      # monotone
    assert objective_cents(res) == Decimal("-333.50")
    assert [(p.product_external_key, p.units) for p in res.purchases] == [
        ("riz_400g", 1)
    ]
    t = res.diagnostic.objective_terms
    assert t.achats_cents == Decimal("180.00")
    assert t.appetence_cents == Decimal("513.50")
    assert t.deplacements_cents == t.temps_cents == t.recuperation_cents == 0


def test_diversity_restores_variety(toy):
    """Calcul manuel 2 : optimum −174,5 c, ≥ 2 recettes, parts ≤ 3.
    Optima multiples (riz 3 + dahl 2 ou riz 2 + dahl 3) : on vérifie la
    VALEUR et la structure, pas l'affectation exacte."""
    res = solve(toy, enable_diversity=True)
    assert res.status == "Optimal"
    assert objective_cents(res) == Decimal("-174.50")
    assert len(res.servings_by_recipe) >= 2
    assert all(x <= 3 for x in res.servings_by_recipe.values())
    assert set(res.servings_by_recipe) == {"riz_nature", "dahl_toy"}
    assert sum(res.servings_by_recipe.values()) in (4, 5)


def test_monotony_documented_in_both_configurations(toy):
    """La paire de comportements exigée par la spec : monotone sans diversité,
    varié avec."""
    assert len(solve(toy).servings_by_recipe) == 1
    assert len(solve(toy, enable_diversity=True).servings_by_recipe) >= 2


def test_batch_fixed_cost_and_time(toy):
    """Calcul manuel 3 : optimum −33,5 c ; τ^fixe pèse via δ_r."""
    res = solve(toy, enable_batch_fixed_cost=True, enable_time_cost=True)
    assert res.status == "Optimal"
    assert res.servings_by_recipe == {"riz_nature": 5}
    assert objective_cents(res) == Decimal("-33.50")
    assert res.diagnostic.objective_terms.temps_cents == Decimal("300.00")
    assert res.cooked_flags.get("riz_nature") is True


def test_pantry_covers_demand(toy):
    """Garde-manger contenant 400 g de riz : plus rien à acheter."""
    problem, pre = toy
    stocked = type(problem)(
        on_date=problem.on_date, profile=problem.profile,
        ingredients=problem.ingredients, recipes=problem.recipes,
        stores=problem.stores, products=problem.products,
        prices=problem.prices, pantry={"riz": Decimal("400")},
    )
    res = PulpMenuSolver().solve(
        stocked, pre, SolverConfig(enable_pantry_stock=True)
    )
    assert res.status == "Optimal"
    assert res.purchases == ()
    assert res.diagnostic.objective_terms.achats_cents == 0
    assert objective_cents(res) == Decimal("-513.50")
    # D13 — valeur du stock consommé, distincte du décaissement (nul ici) :
    # consommé = min(400, 400) = 400 g ; c̄_riz = min(300/1000, 180/400)
    # = 0,30 c/g → 120,00 c de stock déjà payé.
    assert res.diagnostic.pantry_consumed_value_cents == Decimal("120.00")
    assert res.diagnostic.pantry_consumed_by_ingredient["riz"] == {
        "quantite_base_unit": "400", "valeur_cents": "120.00",
    }


def test_salvage_reports_valued_surplus(toy):
    """Diversité forcée à 3 recettes → l'omelette entre, la douzaine d'œufs
    laisse un surplus valorisé : w_œufs = 12 − 2·x_om, σ = 10 c/œuf."""
    res = solve(
        toy, enable_diversity=True, enable_salvage=True, min_distinct_recipes=3
    )
    assert res.status == "Optimal"
    assert "omelette_toy" in res.servings_by_recipe
    x_om = res.servings_by_recipe["omelette_toy"]
    w = res.surplus_by_ingredient.get("oeuf", Decimal(0))
    assert w == Decimal(12 - 2 * x_om)
    valo = Decimal(
        res.diagnostic.surplus_by_ingredient["oeuf"]["valorisation_cents"]
    )
    assert valo == w * Decimal("10")
    # La récupération totale somme TOUS les surplus (les paquets de riz et de
    # lentilles laissent aussi des restes), chacun valorisé à son σ_i.
    total_valo = sum(
        Decimal(v["valorisation_cents"])
        for v in res.diagnostic.surplus_by_ingredient.values()
    )
    assert res.diagnostic.objective_terms.recuperation_cents == total_valo
    assert total_valo >= valo


def test_appetence_constraint_mode(toy):
    """Mode contrainte : Σu·x ≥ U_min sort l'appétence de l'objectif."""
    res = solve(toy, appetence_mode="constraint", appetence_u_min_dollars=5.0)
    assert res.status == "Optimal"
    assert res.diagnostic.objective_terms.appetence_cents == 0
    # U_min = 500 c : 4 portions de riz (429) ne suffisent pas, 5 (513,5) oui.
    assert sum(res.servings_by_recipe.values()) == 5


def test_constraint_mode_requires_u_min():
    with pytest.raises(ValueError):
        SolverConfig(appetence_mode="constraint")


def test_diagnostic_is_complete(toy):
    res = solve(toy, enable_diversity=True)
    d = res.diagnostic
    assert d.effective_params["min_distinct_recipes"]["provenance"] == "profil"
    assert d.prefilter_counts["initial"] == 3
    assert d.demand == {
        "D_exact": "4.0", "borne_basse": "4", "borne_haute": "5",
        "total_retenu": str(sum(res.servings_by_recipe.values())),
    }
    assert len(d.assertions_passed) == 7
    # enable_variant_exclusion est à True par défaut (D16) : il apparaît donc
    # après enable_diversity dans les deux listes, sans qu'on l'ait demandé.
    assert d.last_enabled_flag == "enable_variant_exclusion"
    assert d.flag_effects == {
        "alterent_les_besoins_en_ingredients": [],
        "objectif_ou_contraintes_seulement": [
            "enable_diversity", "enable_variant_exclusion",
        ],
    }
    assert d.distinct_dish_families == d.distinct_recipes  # aucune famille toy
    assert d.max_share_of_demand is not None
    # Cohérence : la somme des termes recompose l'objectif du solveur.
    assert d.objective_terms.total_cents() == objective_cents(res)


def test_override_provenance(toy):
    res = solve(toy, enable_diversity=True, min_distinct_recipes=3)
    p = res.diagnostic.effective_params
    assert p["min_distinct_recipes"] == {
        "valeur": "3", "provenance": "solver_config"
    }
    assert p["max_share_per_recipe"]["provenance"] == "profil"
    assert len(res.servings_by_recipe) >= 3


def test_flags_altering_needs_are_signaled(toy):
    """D11 : les drapeaux qui changent l'équation de couverture (â^fixe via
    enable_batch_fixed_cost, g_i via enable_pantry_stock) sont signalés
    séparément — les paniers ne sont pas comparables entre configurations qui
    en diffèrent."""
    res = solve(toy, enable_batch_fixed_cost=True, enable_pantry_stock=True,
                enable_time_cost=True)
    fx = res.diagnostic.flag_effects
    assert fx["alterent_les_besoins_en_ingredients"] == [
        "enable_batch_fixed_cost", "enable_pantry_stock"
    ]
    # enable_variant_exclusion est à True par défaut (D16) : présent ici sans
    # avoir été demandé, classé côté "objectif_ou_contraintes_seulement"
    # puisqu'il ne touche jamais l'équation de couverture des ingrédients.
    assert fx["objectif_ou_contraintes_seulement"] == [
        "enable_time_cost", "enable_variant_exclusion",
    ]
