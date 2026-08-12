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

import dataclasses
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


def test_locked_recipe_servings_pins_exact_portions(toy):
    """Verrouillage de recette (pilote, docs/product-pilot.md) : x_r fixé à
    3 pour riz_nature (l'optimum non contraint serait 5, calcul manuel 1) —
    le solveur doit respecter le verrou à la portion près, pas seulement
    « au moins 3 »."""
    res = solve(toy, locked_recipe_servings={"riz_nature": 3})
    assert res.status == "Optimal"
    assert res.servings_by_recipe["riz_nature"] == 3
    assert res.cooked_flags["riz_nature"] is True
    # Demande encadrée [4, 5] (D9) toujours respectée par le reste du menu.
    assert 4 <= sum(res.servings_by_recipe.values()) <= 5


def test_batch_fixed_cost_and_time(toy):
    """Calcul manuel 3 : optimum −33,5 c ; τ^fixe pèse via δ_r."""
    res = solve(toy, enable_batch_fixed_cost=True, enable_time_cost=True)
    assert res.status == "Optimal"
    assert res.servings_by_recipe == {"riz_nature": 5}
    assert objective_cents(res) == Decimal("-33.50")
    assert res.diagnostic.objective_terms.temps_cents == Decimal("300.00")
    assert res.cooked_flags.get("riz_nature") is True


def test_confirmed_available_ids_skips_coverage(toy):
    """Confirmation post-génération (pilote, docs/product-pilot.md) :
    ``riz`` confirmé disponible retire la contrainte de couverture — plus
    rien à acheter, sans qu'aucune quantité de stock ne soit injectée nulle
    part (contrairement à l'ancien garde-manger)."""
    res = solve(toy, confirmed_available_ids=("riz",))
    assert res.status == "Optimal"
    assert res.purchases == ()
    assert res.diagnostic.objective_terms.achats_cents == 0
    assert objective_cents(res) == Decimal("-513.50")


def test_staples_bias_purchases_objective_without_changing_real_prices(toy):
    """Essentiels (staples, pilote, docs/product-pilot.md) : ``oeuf`` marqué
    essentiel avec un prix historique bas biaise l'objectif vers
    omelette_toy (diversité forcée, sinon riz seul reste toujours moins cher
    — la comparaison n'aurait rien de discriminant). Le prix RÉEL payé pour
    les œufs (rapporté dans les lignes d'achat) ne doit jamais refléter ce
    biais — seul le choix de recettes en dépend."""
    problem, pre = toy
    biased = dataclasses.replace(
        problem,
        staples=frozenset({"oeuf"}),
        historical_low_price_cents_per_base_unit={"oeuf": Decimal("0.01")},
    )
    baseline = PulpMenuSolver().solve(
        problem, pre, SolverConfig(enable_diversity=True)
    )
    assert baseline.status == "Optimal"
    assert "omelette_toy" not in baseline.servings_by_recipe

    res = PulpMenuSolver().solve(
        biased, pre, SolverConfig(enable_diversity=True, enable_staples=True)
    )
    assert res.status == "Optimal"
    assert "omelette_toy" in res.servings_by_recipe

    egg_lines = [p for p in res.purchases if p.product_external_key == "oeuf_12"]
    assert egg_lines and egg_lines[0].unit_price_cents_cad == 450

    # Sans enable_staples, le même problème (staples/prix historique chargés
    # mais ignorés) reproduit le comportement non biaisé.
    res_no_flag = PulpMenuSolver().solve(biased, pre, SolverConfig(enable_diversity=True))
    assert res_no_flag.status == "Optimal"
    assert "omelette_toy" not in res_no_flag.servings_by_recipe


def test_unknown_salvage_value_is_not_invented(toy):
    """Les valeurs NULL du catalogue ne créent aucun crédit de récupération."""
    problem, pre = toy
    without_salvage = dataclasses.replace(
        problem,
        ingredients={
            iid: dataclasses.replace(
                ingredient, salvage_value_cents_per_base_unit=None
            )
            for iid, ingredient in problem.ingredients.items()
        },
    )
    res = PulpMenuSolver().solve(
        without_salvage,
        pre,
        SolverConfig(
            enable_diversity=True,
            enable_salvage=True,
            min_distinct_recipes=3,
        ),
    )
    assert res.status == "Optimal"
    assert "omelette_toy" in res.servings_by_recipe
    assert res.surplus_by_ingredient == {}
    assert res.diagnostic.surplus_by_ingredient == {}
    assert res.diagnostic.objective_terms.recuperation_cents == 0


def test_perishable_penalty_shifts_recipe_selection(toy):
    """Sixième terme d'objectif (D19, docs/deviations.md) : œuf forcé à
    périssabilité 1,0 (dataclasses.replace, seul ingrédient jouet dont le
    surplus de paquet est significatif — 1 douzaine achetée quel que soit le
    besoin réel). Sans le drapeau, le mélange retenu laisse 10 œufs de
    surplus (omelette_toy=1) ; avec, le solveur bascule vers omelette_toy=3
    (le maximum que permet max_batch_servings) pour absorber le surplus —
    preuve que la pénalité change réellement la sélection, pas seulement
    qu'elle est calculée sans effet. Calibration de RATIO documentée dans
    D19 : un ratio ≤ 0,8 (par analogie avec le plafond de σ_i) n'a AUCUN
    effet sur ce même scénario — vérifié en développant ce test, pas
    supposé."""
    problem, pre = toy
    biased = dataclasses.replace(
        problem,
        ingredients={
            **problem.ingredients,
            "oeuf": dataclasses.replace(
                problem.ingredients["oeuf"], perishability=Decimal("1")
            ),
        },
    )
    kwargs = dict(enable_diversity=True, min_distinct_recipes=3)

    off = PulpMenuSolver().solve(biased, pre, SolverConfig(**kwargs))
    assert off.status == "Optimal"
    assert off.servings_by_recipe.get("omelette_toy", 0) == 1
    assert off.diagnostic.objective_terms.gaspillage_cents == Decimal("0.00")

    on = PulpMenuSolver().solve(
        biased, pre, SolverConfig(**kwargs, enable_perishable_penalty=True)
    )
    assert on.status == "Optimal"
    assert on.servings_by_recipe.get("omelette_toy", 0) == 3
    assert on.diagnostic.objective_terms.gaspillage_cents > Decimal("0.00")

    # Jamais de biais de prix (contrairement aux essentiels/staples) : le
    # prix réel de la douzaine d'œufs reste le même dans les deux plans,
    # seule la sélection de recettes change.
    off_eggs = next(p for p in off.purchases if p.product_external_key == "oeuf_12")
    on_eggs = next(p for p in on.purchases if p.product_external_key == "oeuf_12")
    assert off_eggs.unit_price_cents_cad == on_eggs.unit_price_cents_cad == 450


def test_perishable_penalty_alone_is_independent_of_salvage(toy):
    """enable_perishable_penalty n'a pas besoin de w_i/enable_salvage — sa
    propre variable (gaspillage_i, solver/model.py::_add_perishable_waste)
    est créée et contrainte indépendamment (D19)."""
    res = solve(toy, enable_perishable_penalty=True)
    assert res.status == "Optimal"
    assert res.diagnostic.objective_terms.recuperation_cents == Decimal("0.00")


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
    """D11 : seul le drapeau qui change l'équation de couverture (â^fixe via
    enable_batch_fixed_cost) est signalé séparément. enable_staples n'en
    fait PAS partie — contrairement à l'ancien enable_pantry_stock qu'il
    remplace, il ne change que le prix vu par l'objectif, jamais la
    couverture : un plan avec/sans enable_staples reste comparable."""
    res = solve(toy, enable_batch_fixed_cost=True, enable_staples=True,
                enable_time_cost=True)
    fx = res.diagnostic.flag_effects
    assert fx["alterent_les_besoins_en_ingredients"] == ["enable_batch_fixed_cost"]
    # enable_variant_exclusion est à True par défaut (D16) : présent ici sans
    # avoir été demandé, classé côté "objectif_ou_contraintes_seulement"
    # puisqu'il ne touche jamais l'équation de couverture des ingrédients.
    assert fx["objectif_ou_contraintes_seulement"] == [
        "enable_time_cost", "enable_staples", "enable_variant_exclusion",
    ]
