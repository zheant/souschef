"""Préséance des paramètres — fonction unique (docs/spec.md, schéma
``household``).

``household_profile`` est la source de vérité ; les champs homonymes de
``SolverConfig`` sont des surcharges optionnelles : ``None`` → valeur du
profil. La provenance de chaque valeur effectivement retenue figure dans le
rapport de diagnostic.

Paramètres couverts : K (max_store_visits), R_min (min_distinct_recipes),
α (max_share_per_recipe), ε (demand_slack_epsilon, D9) et U_min
(appetence_u_min_dollars). Le plancher de dépense d'épicerie en faisait partie
jusqu'à son retrait (D40).

U_min détermine aussi le **mode** d'appétence, parce que les deux ne sont pas
indépendants : un plancher sans mode « constraint » ne contraint rien, et le
mode sans plancher est refusé par `SolverConfig`. Le mode effectif est donc
dérivé ici, seul endroit qui voie à la fois le profil et la configuration —
`appetence_mode` sur `SolverConfig` reste la surcharge explicite du mode
développeur, et garde sa validation propre.
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
    appetence_u_min_dollars: EffectiveParam  # U_min (None = aucun plancher)
    #: Plancher de dépense d'épicerie en cents (None = aucun plancher).

    @property
    def appetence_mode(self) -> str:
        """« constraint » dès qu'un plancher est retenu, « objective » sinon."""
        return (
            "constraint"
            if self.appetence_u_min_dollars.value is not None
            else "objective"
        )

    def as_diagnostic(self) -> dict[str, dict]:
        out = {
            name: {"valeur": str(p.value), "provenance": p.source}
            for name, p in vars(self).items()
        }
        out["appetence_mode"] = {"valeur": self.appetence_mode, "provenance": "dérivé"}
        return out


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
        appetence_u_min_dollars=_resolve_u_min(profile, config),
    )


def _resolve_u_min(profile: ProfileData, config: "SolverConfig") -> EffectiveParam:
    """U_min effectif — `_pick` ne suffit pas ici.

    `None` est une valeur significative (aucun plancher), pas seulement
    « rien fourni ». Un `SolverConfig` qui demande explicitement le mode
    « objective » doit donc pouvoir écarter le plancher du profil : c'est ce
    que fait le mode développeur en revenant au crédit dans l'objectif.
    """
    if config.appetence_u_min_dollars is not None:
        return EffectiveParam(Decimal(str(config.appetence_u_min_dollars)), CONFIG)
    if config.appetence_mode == "objective":
        # Surcharge explicite du mode développeur : revenir au crédit dans
        # l'objectif, en écartant le plancher persisté sur le profil.
        return EffectiveParam(None, CONFIG)
    return EffectiveParam(profile.appetence_u_min_dollars, PROFILE)
