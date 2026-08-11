"""Interface du solveur et structures de résultat.

Le solveur est derrière une interface (``MenuSolver``) pour pouvoir être
remplacé — PuLP/CBC aujourd'hui, HiGHS ou autre demain — sans toucher aux
services, à l'API ni au front-end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from ..services.prefilter import PrefilterResult
from ..services.problem_data import ProblemData
from .config import SolverConfig


@dataclass(frozen=True)
class PurchaseLine:
    product_id: int
    product_external_key: str
    store_id: int
    store_external_key: str
    units: int                       # n_ps
    unit_price_cents_cad: int        # c_ps
    taxed_total_cents_cad: Decimal   # n·c·(1+t)
    #: Rabais et économies affichés (pilote, docs/product-pilot.md) — une
    #: lecture du prix résolu, pas un facteur qui influence le choix du
    #: solveur (l'objectif ne connaît que unit_price_cents_cad).
    is_promo: bool = False
    regular_price_cents_cad: int | None = None


@dataclass(frozen=True)
class ObjectiveTerms:
    """Valeur de chaque terme de l'objectif, séparément, en cents CAD.

    Recalculés en Decimal depuis la solution entière — les flottants du
    solveur ne servent qu'à la résolution, jamais au rapport d'argent.
    """

    achats_cents: Decimal
    deplacements_cents: Decimal
    temps_cents: Decimal
    recuperation_cents: Decimal   # crédit : soustrait de l'objectif
    appetence_cents: Decimal      # crédit (mode objective), sinon 0

    def total_cents(self) -> Decimal:
        return (
            self.achats_cents + self.deplacements_cents + self.temps_cents
            - self.recuperation_cents - self.appetence_cents
        )


@dataclass(frozen=True)
class Diagnostic:
    """Rapport de diagnostic — obligatoire (docs/spec.md)."""

    solver_status: str
    solve_time_s: float
    mip_gap_requested: float
    #: CBC via PuLP n'expose pas la borne duale : gap atteint non disponible,
    #: consigné en D11. Le statut « Optimal » de CBC garantit gap ≤ demandé.
    mip_gap_attained: float | None
    objective_terms: ObjectiveTerms | None
    effective_params: dict[str, dict]
    saturated_constraints: dict[str, list[str]]
    prefilter_counts: dict[str, int]
    surplus_by_ingredient: dict[str, dict]      # w_i + valorisation (cents)
    #: Stock du garde-manger consommé par le plan, distinct du décaissement :
    #: Σ_i min(g_i, besoin_i)·c̄_i, avec c̄_i le prix unitaire taxé minimum
    #: courant. Un plan à faible décaissement après un commit n'est pas une
    #: économie — c'est la consommation d'un stock déjà payé ; le front doit
    #: pouvoir afficher les deux lectures (D13).
    pantry_consumed_by_ingredient: dict[str, dict]
    pantry_consumed_value_cents: Decimal
    distinct_recipes: int
    #: Nombre de FAMILLES de plats distinctes retenues (D16) — distinct de
    #: distinct_recipes : deux variantes d'échelle du même plat comptent pour
    #: une seule famille. Avec enable_variant_exclusion actif, les deux
    #: coïncident toujours (au plus une variante par famille) ; sans lui,
    #: distinct_dish_families < distinct_recipes révèle un menu moins varié
    #: que le compte de recettes ne le suggère.
    distinct_dish_families: int
    max_share_of_demand: Decimal | None         # max_r x_r / Σx
    demand: dict[str, str]                      # D exact, bornes, Σx retenu
    #: Signalement obligatoire (D11) : parmi les drapeaux actifs, ceux qui
    #: modifient l'équation de couverture des ingrédients (les paniers ne sont
    #: pas comparables entre configurations qui en diffèrent), distincts de
    #: ceux qui n'altèrent que l'objectif ou les contraintes sur x.
    flag_effects: dict[str, list[str]] = field(default_factory=dict)
    #: En cas d'infaisabilité : IIS indisponible avec CBC → assertions passées
    #: et dernier drapeau activé.
    assertions_passed: list[str] = field(default_factory=list)
    last_enabled_flag: str | None = None
    infeasibility_note: str | None = None


@dataclass(frozen=True)
class SolveResult:
    status: str                                  # Optimal | Infeasible | ...
    servings_by_recipe: dict[str, int]           # x_r > 0 uniquement
    cooked_flags: dict[str, bool]                # δ_r (si présents)
    purchases: tuple[PurchaseLine, ...]
    stores_visited: tuple[str, ...]              # external_keys (z_s = 1)
    surplus_by_ingredient: dict[str, Decimal]    # w_i
    diagnostic: Diagnostic


class MenuSolver(Protocol):
    def solve(
        self,
        problem: ProblemData,
        prefiltered: PrefilterResult,
        config: SolverConfig,
    ) -> SolveResult:
        ...
