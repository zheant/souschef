"""Solveur MILP (PuLP/CBC) — implémentation de l'interface ``MenuSolver``.

Chaque famille de contraintes vit dans une fonction dédiée ``_add_*`` ; chaque
drapeau de ``SolverConfig`` produit un modèle valide et résoluble seul.

Conventions numériques : le modèle est monté en flottants (exigence des
solveurs LP), mais tous les montants rapportés sont **recalculés en Decimal
depuis la solution entière**. L'objectif est en cents CAD.

Adaptations consignées :
- D9 : demande encadrée ⌈D⌉ ≤ Σx_r ≤ ⌈D(1+ε)⌉ ; le plafond de part s'écrit
  x_r ≤ α·⌈D(1+ε)⌉ (constant — cohérent avec la vérification de capacité 6b).
- Big-M agrégé (formule imposée) évalué avec la borne haute de la demande.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from decimal import Decimal

import pulp

from ..services.appetence import RuleBasedAppetenceScorer
from ..services.demand import DemandBounds, compute_demand_bounds
from ..services.params import EffectiveParams, resolve_effective_params
from ..services.prefilter import PrefilterResult
from ..services.problem_data import ProblemData, ProductData, RecipeData
from ..services.travel import TravelCosts, compute_travel_costs, haversine_km
from ..services.needs import ingredient_needs
from ..services.validation import min_taxed_price_per_base_unit, validate_problem
from .config import SolverConfig
from .port import (
    Diagnostic, MenuSolver, ObjectiveTerms, PurchaseLine, SolveResult,
)

_EPS = 1e-6


class _Ctx:
    """Contexte de construction : ensembles, variables, coefficients."""

    def __init__(
        self,
        problem: ProblemData,
        prefiltered: PrefilterResult,
        config: SolverConfig,
        params: EffectiveParams,
        bounds: DemandBounds,
        scorer,
    ):
        self.problem = problem
        self.config = config
        self.params = params
        self.bounds = bounds
        self.recipes: tuple[RecipeData, ...] = prefiltered.surviving
        self.scorer = scorer

        self.stores = self._select_stores()
        store_ids = {s.id for s in self.stores}
        self.products = tuple(
            p for p in problem.products
            if p.canonical_ingredient_id in self._used_ingredients()
        )
        self.price_cents: dict[tuple[int, int], int] = {}
        self.price_is_promo: dict[tuple[int, int], bool] = {}
        #: Référence pour les économies affichées (pilote,
        #: docs/product-pilot.md) — lu par _build_result, jamais par la
        #: résolution elle-même (l'objectif ne connaît que price_cents).
        self.regular_price_cents: dict[tuple[int, int], int | None] = {}
        for pr in problem.prices:
            if pr.store_id in store_ids:
                self.price_cents[(pr.product_id, pr.store_id)] = pr.price_cents_cad
                self.price_is_promo[(pr.product_id, pr.store_id)] = pr.is_promo
                self.regular_price_cents[(pr.product_id, pr.store_id)] = (
                    pr.regular_price_cents_cad
                )
        self.products_by_id: dict[int, ProductData] = {
            p.id: p for p in self.products
        }
        self.pairs = [
            (p, s)
            for p in self.products
            for s in self.stores
            if (p.id, s.id) in self.price_cents
        ]
        # δ_r existe si le coût fixe de lot, la diversité, OU l'exclusion des
        # variantes l'exige (D11, D16).
        self.needs_delta = (
            config.enable_batch_fixed_cost
            or config.enable_diversity
            or config.enable_variant_exclusion
        )
        self.travel: TravelCosts | None = (
            compute_travel_costs(
                problem.profile.home_lat, problem.profile.home_lng, self.stores
            )
            if config.enable_multi_store
            else None
        )

        self.x: dict = {}
        self.xk: dict = {}   # segments d'utilité : (recipe_id, k) → var
        self.delta: dict = {}
        self.n: dict = {}
        self.z: dict = {}
        self.v: dict = {}    # visite de centre commercial
        self.y = None
        self.w: dict = {}

    def _used_ingredients(self) -> set[str]:
        return {
            ri.canonical_ingredient_id
            for r in self.recipes
            for ri in r.ingredients
        }

    def _select_stores(self):
        if self.config.enable_multi_store:
            return self.problem.stores
        key = self.config.single_store_external_key
        if key is not None:
            chosen = [s for s in self.problem.stores if s.external_key == key]
            if not chosen:
                raise ValueError(f"single_store_external_key '{key}' inconnu.")
            return tuple(chosen)
        # Règle déterministe : le plus proche du domicile (D11).
        home = (self.problem.profile.home_lat, self.problem.profile.home_lng)
        nearest = min(
            self.problem.stores,
            key=lambda s: (haversine_km(*home, s.lat, s.lng), s.external_key),
        )
        return (nearest,)

    # -- Quantité requise de l'ingrédient i, expression PuLP -----------------
    def demand_expr(self, ingredient_id: str):
        terms = []
        for r in self.recipes:
            for ri in r.ingredients:
                if ri.canonical_ingredient_id != ingredient_id:
                    continue
                terms.append(
                    float(ri.qty_marginal_per_serving_base_unit) * self.x[r.id]
                )
                if (
                    self.config.enable_batch_fixed_cost
                    and ri.qty_fixed_per_batch_base_unit
                ):
                    terms.append(
                        float(ri.qty_fixed_per_batch_base_unit) * self.delta[r.id]
                    )
        return pulp.lpSum(terms)

    def supply_expr(self, ingredient_id: str):
        pantry = (
            float(self.problem.pantry.get(ingredient_id, 0))
            if self.config.enable_pantry_stock
            else 0.0
        )
        return (
            pulp.lpSum(
                float(p.package_qty_in_base_unit) * self.n[(p.id, s.id)]
                for (p, s) in self.pairs
                if p.canonical_ingredient_id == ingredient_id
            )
            + pantry
        )


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

#: Drapeaux qui modifient l'équation de couverture des ingrédients — les
#: paniers ne sont PAS comparables entre configurations qui en diffèrent
#: (signalement obligatoire, docs/deviations.md D11) :
#: - enable_batch_fixed_cost : retire/ajoute â^fixe_ir aux besoins ;
#: - enable_pantry_stock : retire/ajoute g_i à l'approvisionnement.
FLAGS_ALTERING_NEEDS = frozenset(
    {"enable_batch_fixed_cost", "enable_pantry_stock"}
)


def _flag_signaling(config: SolverConfig) -> dict[str, list[str]]:
    enabled = config.enabled_flags()
    return {
        "alterent_les_besoins_en_ingredients": [
            f for f in enabled if f in FLAGS_ALTERING_NEEDS
        ],
        "objectif_ou_contraintes_seulement": [
            f for f in enabled if f not in FLAGS_ALTERING_NEEDS
        ],
    }


def _add_variables(m: pulp.LpProblem, c: _Ctx) -> None:
    # Noms de variables/contraintes construits depuis les clés de
    # substitution (p.id, s.id), jamais depuis external_key : ce dernier est
    # un concept de couche d'ingestion, instable par nature (D15/D18,
    # docs/deviations.md) — le solveur ne doit dépendre que de garanties
    # d'unicité internes à la base. Exception assumée : le tri du bris de
    # symétrie (_add_symmetry_breaking) reste sur external_key, qui y est une
    # règle métier (ordre lexicographique déterministe), pas un identifiant.
    for r in c.recipes:
        c.x[r.id] = pulp.LpVariable(f"x_{r.id}", lowBound=0, cat=pulp.LpInteger)
        for k, seg in enumerate(c.scorer.utility_segments(r)):
            c.xk[(r.id, k)] = pulp.LpVariable(
                f"xk_{r.id}_{k}", lowBound=0, upBound=seg.max_portions,
                cat=pulp.LpInteger,
            )
        m += c.x[r.id] == pulp.lpSum(
            c.xk[(r.id, k)]
            for k in range(len(c.scorer.utility_segments(r)))
        ), f"segments_{r.id}"
        if c.needs_delta:
            c.delta[r.id] = pulp.LpVariable(f"delta_{r.id}", cat=pulp.LpBinary)
    for (p, s) in c.pairs:
        c.n[(p.id, s.id)] = pulp.LpVariable(
            f"n_{p.id}_{s.id}", lowBound=0, cat=pulp.LpInteger
        )
    if c.config.enable_multi_store:
        for s in c.stores:
            c.z[s.id] = pulp.LpVariable(f"z_{s.id}", cat=pulp.LpBinary)
        for center in c.travel.center_stores:
            c.v[center] = pulp.LpVariable(f"v_{center}", cat=pulp.LpBinary)
        c.y = pulp.LpVariable("y", cat=pulp.LpBinary)
    if c.config.enable_salvage:
        for iid in c._used_ingredients():
            c.w[iid] = pulp.LpVariable(f"w_{iid}", lowBound=0)


# ---------------------------------------------------------------------------
# Familles de contraintes — une fonction dédiée chacune
# ---------------------------------------------------------------------------

def _add_demand(m: pulp.LpProblem, c: _Ctx) -> None:
    """⌈D⌉ ≤ Σx_r ≤ ⌈D(1+ε)⌉ (D9)."""
    total = pulp.lpSum(c.x.values())
    m += total >= c.bounds.low, "demande_basse"
    m += total <= c.bounds.high, "demande_haute"


def _add_coverage(m: pulp.LpProblem, c: _Ctx) -> None:
    """Couverture des ingrédients, stock initial inclus."""
    for iid in sorted(c._used_ingredients()):
        m += (
            c.supply_expr(iid) >= c.demand_expr(iid),
            f"couverture_{iid}",
        )


def _add_batch_coherence(m: pulp.LpProblem, c: _Ctx) -> None:
    """β_r·δ_r ≤ x_r ≤ m_r·δ_r — ou lien minimal x_r ≥ δ_r si seul
    l'indicateur de diversité est requis (D11)."""
    for r in c.recipes:
        if c.needs_delta:
            lower = (
                r.min_batch_servings if c.config.enable_batch_fixed_cost else 1
            )
            m += c.x[r.id] >= lower * c.delta[r.id], f"lot_min_{r.id}"
            m += c.x[r.id] <= r.max_batch_servings * c.delta[r.id], f"lot_max_{r.id}"
        else:
            m += c.x[r.id] <= r.max_batch_servings, f"lot_max_{r.id}"


def _add_locked_recipes(m: pulp.LpProblem, c: _Ctx) -> None:
    """x_r fixé exactement pour chaque recette verrouillée (pilote,
    docs/product-pilot.md) — pas seulement δ_r = 1 : « une réoptimisation ne
    change jamais silencieusement les recettes verrouillées » implique le
    nombre de portions aussi. Inconditionnel (pas de nouveau enable_* — la
    présence de config.locked_recipe_servings EST le drapeau), no-op si
    vide. ``rid in c.x`` est garanti par la validation faite en amont dans
    services/planning.py::reoptimize_plan (après préfiltrage) — pas de
    branche défensive ici. L'exclusion mutuelle de variantes (D16,
    _add_variant_exclusion) protège déjà contre le verrouillage simultané
    de deux variantes d'un même plat."""
    for rid, servings in c.config.locked_recipe_servings.items():
        m += c.x[rid] == servings, f"verrouillage_{rid}"
        if rid in c.delta:
            m += c.delta[rid] == 1, f"verrouillage_delta_{rid}"


#: Fraction minimale du stock déclaré qu'un ingrédient « doit être utilisé »
#: doit voir consommée (pilote, docs/product-pilot.md) — pas 1,0 : « cette
#: contrainte ne signifie pas automatiquement que toute la quantité doit
#: être consommée, puisque les quantités déclarées peuvent être
#: approximatives ». Constante système, pas configurable par l'utilisateur
#: (le produit ne demande qu'un bouton, pas un curseur).
MUST_USE_PANTRY_MIN_FRACTION = 0.5


def _add_must_use_pantry(m: pulp.LpProblem, c: _Ctx) -> None:
    """demand_expr(i) ≥ 0,5·g_i pour chaque ingrédient marqué « doit être
    utilisé » (pilote, docs/product-pilot.md) — réutilise demand_expr, déjà
    là pour la couverture, pas de nouveau calcul de besoin. Inconditionnel
    (tuple vide = no-op) mais sans effet si enable_pantry_stock est
    inactif : g_i n'est même pas dans le modèle sans ce drapeau, imposer une
    fraction d'un stock qui n'existe pas dans le modèle n'aurait aucun sens.
    """
    if not c.config.enable_pantry_stock:
        return
    for iid in c.config.must_use_pantry_ids:
        g_i = float(c.problem.pantry.get(iid, 0))
        if g_i <= 0:
            continue
        m += (
            c.demand_expr(iid) >= MUST_USE_PANTRY_MIN_FRACTION * g_i,
            f"doit_utiliser_{iid}",
        )


def _add_diversity(m: pulp.LpProblem, c: _Ctx) -> None:
    """Σδ_r ≥ R_min et x_r ≤ α·⌈D(1+ε)⌉."""
    r_min = int(c.params.min_distinct_recipes.value)
    alpha = float(c.params.max_share_per_recipe.value)
    m += pulp.lpSum(c.delta.values()) >= r_min, "diversite_r_min"
    cap = alpha * c.bounds.high
    for r in c.recipes:
        m += c.x[r.id] <= cap, f"part_max_{r.id}"


def _add_variant_exclusion(m: pulp.LpProblem, c: _Ctx) -> None:
    """Σ_{r ∈ famille} δ_r ≤ 1, pour chaque famille de plat comptant plus
    d'une variante parmi les recettes survivantes (D16, docs/deviations.md).

    Les variantes d'échelle (format régulier / familial) sont deux segments
    d'une même courbe de coût non linéaire pour PRODUIRE UN SEUL PLAT — pas
    deux plats. Sans cette contrainte, le solveur peut cuisiner les deux
    variantes du même plat : chacune reste sous le plafond de part
    x_r ≤ α·⌈D(1+ε)⌉ individuellement, mais leur somme ne l'est pas — un
    contournement structurel du plafond, et un gonflement du compte de
    diversité Σδ_r ≥ R_min sans varier réellement le menu. Payer τ_fixe deux
    fois pour le même plat n'a par ailleurs aucun sens culinaire.
    """
    families: dict[str, list[str]] = defaultdict(list)
    for r in c.recipes:
        families[r.dish_family_id].append(r.id)
    for family_id, rids in families.items():
        if len(rids) > 1:
            m += (
                pulp.lpSum(c.delta[rid] for rid in rids) <= 1,
                f"exclusion_variante_{family_id}",
            )


def _big_m(c: _Ctx, product: ProductData) -> int:
    """Big-M agrégé (formule imposée) : borne fondée sur la demande TOTALE,
    jamais sur une seule recette."""
    iid = product.canonical_ingredient_id
    worst = max(
        (
            float(
                ri.qty_marginal_per_serving_base_unit
                + ri.qty_fixed_per_batch_base_unit
            )
            for r in c.recipes
            for ri in r.ingredients
            if ri.canonical_ingredient_id == iid
        ),
        default=0.0,
    )
    return math.ceil(
        c.bounds.high * worst / float(product.package_qty_in_base_unit)
    )


def _add_store_linking(m: pulp.LpProblem, c: _Ctx) -> None:
    """n_ps ≤ M_ps·z_s ; y ≥ z_s ; Σz_s ≤ K ; liens centre commercial."""
    for (p, s) in c.pairs:
        m += c.n[(p.id, s.id)] <= _big_m(c, p) * c.z[s.id], f"lien_{p.id}_{s.id}"
    for s in c.stores:
        m += c.y >= c.z[s.id], f"sortie_{s.id}"
    m += (
        pulp.lpSum(c.z.values()) <= int(c.params.max_store_visits.value),
        "plafond_arrets",
    )
    for center, sids in c.travel.center_stores.items():
        for sid in sids:
            m += c.v[center] >= c.z[sid], f"centre_{center}_{sid}"


def _add_surplus(m: pulp.LpProblem, c: _Ctx) -> None:
    """w_i ≤ approvisionnement − besoin. Inégalité ≤, jamais ≥ ni = : avec un
    ≥ le solveur gonflerait w_i et l'objectif partirait à −∞ ; le ≤ suffit,
    l'optimum le sature naturellement."""
    for iid, w in c.w.items():
        m += w <= c.supply_expr(iid) - c.demand_expr(iid), f"surplus_{iid}"


def _add_symmetry_breaking(m: pulp.LpProblem, c: _Ctx) -> None:
    """À prix taxé égal pour un même produit, ordre lexicographique des
    magasins : le magasin lexicographiquement second ne sert ce produit que si
    le premier n'est pas visité."""
    by_product: dict[int, list] = defaultdict(list)
    for (p, s) in c.pairs:
        by_product[p.id].append(s)
    for p_id, stores in by_product.items():
        product = c.products_by_id[p_id]
        by_price: dict[int, list] = defaultdict(list)
        for s in stores:
            by_price[c.price_cents[(p_id, s.id)]].append(s)
        for group in by_price.values():
            group.sort(key=lambda s: s.external_key)
            for i, first in enumerate(group):
                for second in group[i + 1:]:
                    m += (
                        c.n[(p_id, second.id)]
                        <= _big_m(c, product) * (1 - c.z[first.id]),
                        f"symetrie_{product.id}_{first.id}_{second.id}",
                    )


def _add_appetence_constraint(m: pulp.LpProblem, c: _Ctx) -> None:
    """Mode « constraint » : Σ u_rk·x_rk ≥ U_min (en cents)."""
    u_min_cents = float(Decimal(str(c.config.appetence_u_min_dollars)) * 100)
    m += _appetence_expr_cents(c) >= u_min_cents, "appetence_min"


# ---------------------------------------------------------------------------
# Termes de l'objectif
# ---------------------------------------------------------------------------

def _purchases_expr_cents(c: _Ctx):
    return pulp.lpSum(
        float(
            Decimal(c.price_cents[(p.id, s.id)]) * (1 + p.tax_rate)
        ) * c.n[(p.id, s.id)]
        for (p, s) in c.pairs
    )


def _travel_expr_cents(c: _Ctx):
    t = c.travel
    return (
        t.f_sortie_cents * c.y
        + pulp.lpSum(
            float(t.center_anchor_cents[center]) * c.v[center]
            for center in t.center_stores
        )
        + pulp.lpSum(float(t.per_stop_cents) * z for z in c.z.values())
    )


def _time_expr_cents(c: _Ctx):
    kappa = c.problem.profile.time_value_cents_per_hour
    terms = [
        kappa * float(r.prep_time_marginal_h) * c.x[r.id] for r in c.recipes
    ]
    if c.config.enable_batch_fixed_cost:
        terms += [
            kappa * float(r.prep_time_fixed_h) * c.delta[r.id] for r in c.recipes
        ]
    return pulp.lpSum(terms)


def _salvage_expr_cents(c: _Ctx):
    return pulp.lpSum(
        float(c.problem.ingredients[iid].salvage_value_cents_per_base_unit) * w
        for iid, w in c.w.items()
    )


def _appetence_expr_cents(c: _Ctx):
    terms = []
    for r in c.recipes:
        for k, seg in enumerate(c.scorer.utility_segments(r)):
            terms.append(
                float(seg.marginal_u_per_serving * 100) * c.xk[(r.id, k)]
            )
    return pulp.lpSum(terms)


# ---------------------------------------------------------------------------
# Solveur
# ---------------------------------------------------------------------------

class PulpMenuSolver:
    """Implémentation PuLP/CBC de l'interface MenuSolver.

    ``scorer_factory`` : fabrique AppetenceScorer(problem) — RuleBased par
    défaut, remplaçable (modèle appris, mise à l'échelle pour analyse de
    sensibilité) sans toucher au modèle MILP.
    """

    def __init__(self, scorer_factory=RuleBasedAppetenceScorer):
        self._scorer_factory = scorer_factory

    def solve(
        self,
        problem: ProblemData,
        prefiltered: PrefilterResult,
        config: SolverConfig,
    ) -> SolveResult:
        params = resolve_effective_params(problem.profile, config)
        assertions_passed, _ = validate_problem(problem, prefiltered.surviving)
        bounds = compute_demand_bounds(
            problem.profile.meals_per_horizon,
            list(problem.profile.appetite_coefficients),
            Decimal(str(params.demand_slack_epsilon.value)),
        )
        c = _Ctx(
            problem, prefiltered, config, params, bounds,
            self._scorer_factory(problem),
        )

        m = pulp.LpProblem("menu_optimizer", pulp.LpMinimize)
        _add_variables(m, c)
        _add_demand(m, c)
        _add_coverage(m, c)
        _add_batch_coherence(m, c)
        _add_locked_recipes(m, c)
        _add_must_use_pantry(m, c)
        if config.enable_diversity:
            _add_diversity(m, c)
        if config.enable_variant_exclusion:
            _add_variant_exclusion(m, c)
        if config.enable_multi_store:
            _add_store_linking(m, c)
            _add_symmetry_breaking(m, c)
        if config.enable_salvage:
            _add_surplus(m, c)
        if config.appetence_mode == "constraint":
            _add_appetence_constraint(m, c)

        objective = _purchases_expr_cents(c)
        if config.enable_multi_store:
            objective += _travel_expr_cents(c)
        if config.enable_time_cost:
            objective += _time_expr_cents(c)
        if config.enable_salvage:
            objective -= _salvage_expr_cents(c)
        if config.appetence_mode == "objective":
            objective -= _appetence_expr_cents(c)
        m += objective

        t0 = time.monotonic()
        m.solve(
            pulp.PULP_CBC_CMD(
                msg=0,
                timeLimit=config.solver_time_limit_s,
                gapRel=config.mip_gap,
            )
        )
        elapsed = time.monotonic() - t0
        status = pulp.LpStatus[m.status]

        if status != "Optimal":
            diag = self._diagnostic_infeasible(
                c, status, elapsed, assertions_passed, prefiltered
            )
            return SolveResult(
                status=status, servings_by_recipe={}, cooked_flags={},
                purchases=(), stores_visited=(), surplus_by_ingredient={},
                diagnostic=diag,
            )
        return self._build_result(
            c, m, status, elapsed, assertions_passed, prefiltered
        )

    # -- Extraction et diagnostic ------------------------------------------

    def _build_result(self, c, m, status, elapsed, assertions_passed, prefiltered):
        cfg = c.config
        x_val = {
            rid: int(round(v.value() or 0)) for rid, v in c.x.items()
        }
        servings = {rid: x for rid, x in x_val.items() if x > 0}
        cooked = {rid: bool(round(v.value() or 0)) for rid, v in c.delta.items()}

        purchases: list[PurchaseLine] = []
        for (p, s) in c.pairs:
            units = int(round(c.n[(p.id, s.id)].value() or 0))
            if units == 0:
                continue
            cents = c.price_cents[(p.id, s.id)]
            purchases.append(
                PurchaseLine(
                    product_id=p.id, product_external_key=p.external_key,
                    store_id=s.id, store_external_key=s.external_key,
                    units=units, unit_price_cents_cad=cents,
                    taxed_total_cents_cad=(
                        Decimal(units) * Decimal(cents) * (1 + p.tax_rate)
                    ).quantize(Decimal("0.01")),
                    is_promo=c.price_is_promo.get((p.id, s.id), False),
                    regular_price_cents_cad=c.regular_price_cents.get((p.id, s.id)),
                )
            )

        visited = tuple(
            s.external_key for s in c.stores
            if not cfg.enable_multi_store or round(c.z[s.id].value() or 0)
        ) if purchases else ()

        surplus = {
            iid: Decimal(str(w.value() or 0)).quantize(Decimal("0.001"))
            for iid, w in c.w.items()
            if (w.value() or 0) > _EPS
        }

        terms = self._objective_terms(c, servings, cooked, purchases, surplus, visited)
        total = sum(servings.values())
        saturated = self._saturated(c, m, servings, visited)
        pantry_consumed, pantry_value = self._pantry_consumption(c, servings, cooked)

        diag = Diagnostic(
            solver_status=status,
            solve_time_s=round(elapsed, 3),
            mip_gap_requested=cfg.mip_gap,
            mip_gap_attained=None,
            objective_terms=terms,
            effective_params=c.params.as_diagnostic(),
            saturated_constraints=saturated,
            prefilter_counts=prefiltered.counts_by_stage,
            surplus_by_ingredient={
                iid: {
                    "quantite_base_unit": str(q),
                    "valorisation_cents": str(
                        (q * c.problem.ingredients[iid]
                         .salvage_value_cents_per_base_unit)
                        .quantize(Decimal("0.01"))
                    ),
                }
                for iid, q in surplus.items()
            },
            pantry_consumed_by_ingredient=pantry_consumed,
            pantry_consumed_value_cents=pantry_value,
            distinct_recipes=len(servings),
            distinct_dish_families=len(
                {r.dish_family_id for r in c.recipes if servings.get(r.id, 0) > 0}
            ),
            max_share_of_demand=(
                (Decimal(max(servings.values())) / Decimal(total))
                .quantize(Decimal("0.001"))
                if servings else None
            ),
            demand={
                "D_exact": str(c.bounds.exact),
                "borne_basse": str(c.bounds.low),
                "borne_haute": str(c.bounds.high),
                "total_retenu": str(total),
            },
            flag_effects=_flag_signaling(cfg),
            assertions_passed=assertions_passed,
            last_enabled_flag=(cfg.enabled_flags() or [None])[-1],
        )
        return SolveResult(
            status=status, servings_by_recipe=servings, cooked_flags=cooked,
            purchases=tuple(purchases), stores_visited=visited,
            surplus_by_ingredient=surplus, diagnostic=diag,
        )

    def _objective_terms(self, c, servings, cooked, purchases, surplus, visited):
        cfg = c.config
        achats = sum(
            (line.taxed_total_cents_cad for line in purchases), Decimal(0)
        )
        deplacements = Decimal(0)
        if cfg.enable_multi_store and visited:
            t = c.travel
            visited_ids = {
                s.id for s in c.stores if s.external_key in set(visited)
            }
            deplacements += Decimal(t.f_sortie_cents)
            for center, sids in t.center_stores.items():
                if any(sid in visited_ids for sid in sids):
                    deplacements += t.center_anchor_cents[center]
            deplacements += t.per_stop_cents * len(visited_ids)
        temps = Decimal(0)
        if cfg.enable_time_cost:
            kappa = Decimal(c.problem.profile.time_value_cents_per_hour)
            for r in c.recipes:
                temps += kappa * r.prep_time_marginal_h * servings.get(r.id, 0)
                if cfg.enable_batch_fixed_cost and cooked.get(r.id):
                    temps += kappa * r.prep_time_fixed_h
        recuperation = sum(
            (
                q * c.problem.ingredients[iid].salvage_value_cents_per_base_unit
                for iid, q in surplus.items()
            ),
            Decimal(0),
        )
        appetence = Decimal(0)
        if cfg.appetence_mode == "objective":
            for r in c.recipes:
                remaining = servings.get(r.id, 0)
                for seg in c.scorer.utility_segments(r):
                    take = min(remaining, seg.max_portions)
                    appetence += seg.marginal_u_per_serving * 100 * take
                    remaining -= take
        return ObjectiveTerms(
            achats_cents=achats.quantize(Decimal("0.01")),
            deplacements_cents=deplacements.quantize(Decimal("0.01")),
            temps_cents=temps.quantize(Decimal("0.01")),
            recuperation_cents=recuperation.quantize(Decimal("0.01")),
            appetence_cents=appetence.quantize(Decimal("0.01")),
        )

    def _pantry_consumption(self, c, servings, cooked):
        """Σ min(g_i, besoin_i)·c̄_i — valeur du stock déjà payé consommé par
        ce plan (D13). Zéro si le garde-manger n'était pas dans le modèle."""
        if not c.config.enable_pantry_stock or not c.problem.pantry:
            return {}, Decimal("0.00")
        needs = ingredient_needs(
            c.problem, servings, cooked,
            include_fixed=c.config.enable_batch_fixed_cost,
        )
        unit_price = min_taxed_price_per_base_unit(c.problem)
        detail: dict[str, dict] = {}
        total = Decimal(0)
        for iid, g in c.problem.pantry.items():
            consumed = min(g, needs.get(iid, Decimal(0)))
            if consumed <= 0:
                continue
            value = (consumed * unit_price.get(iid, Decimal(0))).quantize(
                Decimal("0.01")
            )
            detail[iid] = {
                "quantite_base_unit": str(consumed),
                "valeur_cents": str(value),
            }
            total += value
        return detail, total.quantize(Decimal("0.01"))

    def _saturated(self, c, m, servings, visited) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {
            "couvertures_ingredients": [], "plafond_arrets": [], "diversite": [],
            "demande": [],
        }
        # Une couverture 0 ≥ 0 a un slack nul mais ne contraint rien : seuls
        # les ingrédients réellement demandés par le menu retenu comptent.
        demanded: set[str] = set()
        for r in c.recipes:
            if servings.get(r.id, 0) > 0:
                demanded.update(
                    ri.canonical_ingredient_id for ri in r.ingredients
                )
        for name, cons in m.constraints.items():
            slack = cons.slack
            if slack is None or abs(slack) > 1e-4:
                continue
            if name.startswith("couverture_"):
                iid = name.removeprefix("couverture_")
                if iid in demanded:
                    out["couvertures_ingredients"].append(iid)
            elif name == "plafond_arrets":
                out["plafond_arrets"].append(
                    f"K = {int(c.params.max_store_visits.value)} atteint"
                )
            elif (
                name == "diversite_r_min"
                or name.startswith("part_max_")
                or name.startswith("exclusion_variante_")
            ):
                out["diversite"].append(name)
            elif name.startswith("demande_"):
                out["demande"].append(name)
        return out

    def _diagnostic_infeasible(
        self, c, status, elapsed, assertions_passed, prefiltered
    ) -> Diagnostic:
        cfg = c.config
        return Diagnostic(
            solver_status=status,
            solve_time_s=round(elapsed, 3),
            mip_gap_requested=cfg.mip_gap,
            mip_gap_attained=None,
            objective_terms=None,
            effective_params=c.params.as_diagnostic(),
            saturated_constraints={},
            prefilter_counts=prefiltered.counts_by_stage,
            surplus_by_ingredient={},
            pantry_consumed_by_ingredient={},
            pantry_consumed_value_cents=Decimal("0"),
            distinct_recipes=0,
            distinct_dish_families=0,
            max_share_of_demand=None,
            demand={
                "D_exact": str(c.bounds.exact),
                "borne_basse": str(c.bounds.low),
                "borne_haute": str(c.bounds.high),
            },
            flag_effects=_flag_signaling(cfg),
            assertions_passed=assertions_passed,
            last_enabled_flag=(cfg.enabled_flags() or [None])[-1],
            infeasibility_note=(
                "IIS indisponible avec CBC ; toutes les assertions pré-solveur "
                "sont passées — l'infaisabilité vient de l'interaction des "
                "contraintes actives, en dernier lieu du drapeau "
                f"'{(cfg.enabled_flags() or ['aucun'])[-1]}'."
            ),
        )


_solver_check: MenuSolver = PulpMenuSolver()  # vérification statique du contrat
