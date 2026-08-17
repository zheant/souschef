"""Couche services.

Les ré-exports sont résolus à la demande (PEP 562) plutôt qu'à l'import du
paquet. Sans cela, importer un module *pur* de cette couche — le calcul de prix
d'une recette, le contrôle de vraisemblance, l'audit de couverture — tirait toute
la couche base de données avec lui : leur docstring promet de ne connaître ni
SQLAlchemy ni HTTP, et l'ADR de sémantique des prix promet des rapports
calculables sans PostgreSQL. Ces promesses ne tenaient qu'à la présence de la
dépendance dans l'environnement.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — confort d'outillage uniquement
    from .appetence import AppetenceScorer, RuleBasedAppetenceScorer
    from .demand import DemandBounds, compute_demand_bounds
    from .prefilter import PrefilterResult, prefilter_recipes
    from .problem_data import ProblemData, load_problem_data
    from .units import convert_qty
    from .validation import ValidationError, validate_problem

_EXPORTS = {
    "AppetenceScorer": "appetence",
    "RuleBasedAppetenceScorer": "appetence",
    "DemandBounds": "demand",
    "compute_demand_bounds": "demand",
    "PrefilterResult": "prefilter",
    "prefilter_recipes": "prefilter",
    "ProblemData": "problem_data",
    "load_problem_data": "problem_data",
    "convert_qty": "units",
    "ValidationError": "validation",
    "validate_problem": "validation",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} n'expose pas {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{module_name}", __name__), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
