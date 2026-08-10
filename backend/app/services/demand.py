"""Demande du ménage — encadrement décidé au point de contrôle de l'étape 2
(docs/deviations.md, D9).

L'égalité stricte Σx_r = D de la spec initiale rendait le problème infaisable
dès que D = n_repas·Σρ_h n'était pas entier (les ρ_h sont des coefficients
d'appétit : deux adultes et un enfant sur 14 repas donnent D = 36,4). La
contrainte retenue est :

    ⌈D⌉ ≤ Σ_r x_r ≤ ⌈D(1+ε)⌉

La borne basse garantit que le ménage mange, la borne haute empêche la
surproduction, la marge ε donne au solveur la latitude d'ajuster les portions
aux formats d'emballage. ε vit dans ``household_profile``
(``demand_slack_epsilon``, défaut 0,10) et sera surchargeable par
``SolverConfig`` via la fonction unique de résolution des paramètres (étape 4).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class DemandBounds:
    #: D exact = n_repas · Σ_h ρ_h — potentiellement fractionnaire.
    exact: Decimal
    #: ⌈D⌉ — borne basse de Σx_r.
    low: int
    #: ⌈D(1+ε)⌉ — borne haute de Σx_r.
    high: int
    epsilon: Decimal


def compute_demand_bounds(
    meals_per_horizon: int,
    appetite_coefficients: list[Decimal],
    epsilon: Decimal,
) -> DemandBounds:
    if meals_per_horizon <= 0:
        raise ValueError("meals_per_horizon doit être > 0")
    if epsilon < 0:
        raise ValueError("demand_slack_epsilon doit être ≥ 0")
    exact = Decimal(meals_per_horizon) * sum(appetite_coefficients, Decimal(0))
    low = math.ceil(exact)
    high = math.ceil(exact * (1 + epsilon))
    return DemandBounds(exact=exact, low=low, high=high, epsilon=epsilon)
