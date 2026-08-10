"""Préséance des paramètres — fonction unique (docs/spec.md, schéma
``household``).

``household_profile`` est la source de vérité ; les champs homonymes de
``SolverConfig`` sont des surcharges optionnelles : ``None`` → valeur du
profil. La provenance de chaque valeur effectivement retenue figure dans le
rapport de diagnostic.

Paramètres couverts : K (max_store_visits), R_min (min_distinct_recipes),
α (max_share_per_recipe) et, depuis D9, ε (demand_slack_epsilon).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from .problem_data import ProfileData

if TYPE_CHECKING:  # import différé — évite le cycle services ↔ solver
    from ..solver.config import SolverConfig

PROFILE = "profil"
CONFIG = "solver_config"


@dataclass(frozen=True)
class EffectiveParam:
    value: object
    source: str  # PROFILE | CONFIG


@dataclass(frozen=True)
class EffectiveParams:
    max_store_visits: EffectiveParam       # K
    min_distinct_recipes: EffectiveParam   # R_min
    max_share_per_recipe: EffectiveParam   # α
    demand_slack_epsilon: EffectiveParam   # ε (D9)

    def as_diagnostic(self) -> dict[str, dict]:
        return {
            name: {"valeur": str(p.value), "provenance": p.source}
            for name, p in vars(self).items()
        }


def _pick(override, profile_value) -> EffectiveParam:
    if override is None:
        return EffectiveParam(profile_value, PROFILE)
    return EffectiveParam(override, CONFIG)


def resolve_effective_params(
    profile: ProfileData, config: "SolverConfig"
) -> EffectiveParams:
    """LA fonction de résolution : aucune autre lecture croisée
    profil/SolverConfig n'est autorisée ailleurs."""
    return EffectiveParams(
        max_store_visits=_pick(config.max_store_visits, profile.max_store_visits),
        min_distinct_recipes=_pick(
            config.min_distinct_recipes, profile.min_distinct_recipes
        ),
        max_share_per_recipe=_pick(
            Decimal(str(config.max_share_per_recipe))
            if config.max_share_per_recipe is not None
            else None,
            profile.max_share_per_recipe,
        ),
        demand_slack_epsilon=_pick(
            Decimal(str(config.demand_slack_epsilon))
            if config.demand_slack_epsilon is not None
            else None,
            profile.demand_slack_epsilon,
        ),
    )
