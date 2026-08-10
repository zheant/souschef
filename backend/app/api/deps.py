"""Dépendances FastAPI — les points d'injection de l'application.

``get_solver`` retourne l'implémentation concrète du MenuSolver ; les tests
(et demain un autre solveur) la remplacent par dependency_overrides sans
toucher aux routes.
"""

from collections.abc import Iterator

from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..solver import MenuSolver, PulpMenuSolver


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
        session.commit()


def get_solver() -> MenuSolver:
    return PulpMenuSolver()


def get_profile_id() -> str:
    # v1 : un seul profil de ménage, chargé depuis la configuration.
    return settings.household_profile_id
