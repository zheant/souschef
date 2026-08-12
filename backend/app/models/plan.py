"""Plans persistés (schéma ``household``).

Table absente du modèle de données de la spec mais exigée par son API
(``GET /api/plan/{id}``, ``POST /api/plan/{id}/commit``) — ajout consigné en
D12. Le plan stocke tout ce qu'il faut pour rendre le ``commit`` déterministe
(portions, achats, besoins par ingrédient, config) et pour alimenter la
pénalité de répétition du scorer (recettes des derniers plans commis).
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow

SCHEMA = "household"


class PlanStatus(str, enum.Enum):
    proposed = "proposed"
    committed = "committed"


class Plan(Base):
    __tablename__ = "plan"
    __table_args__ = (
        Index("ix_plan_profile_status", "household_profile_id", "status"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    household_profile_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA}.household_profile.id", ondelete="CASCADE")
    )
    status: Mapped[PlanStatus] = mapped_column(
        Enum(PlanStatus, name="plan_status", schema=SCHEMA),
        default=PlanStatus.proposed,
    )
    on_date: Mapped[date]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    committed_at: Mapped[datetime | None]
    solver_status: Mapped[str] = mapped_column(String(32))
    #: SolverConfig sérialisée — persistée pour audit/diagnostic, pas relue
    #: au commit (devenu une simple validation + passage de statut).
    config: Mapped[dict] = mapped_column(JSONB)
    #: x_r par recette (id → portions).
    servings: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: δ_r par recette.
    cooked: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: Lignes d'achat sérialisées (produit, magasin, unités, prix).
    purchases: Mapped[list] = mapped_column(JSONB, default=list)
    #: Besoins par ingrédient (id → quantité en base_unit, str décimale) —
    #: figés à la résolution pour un commit déterministe.
    ingredient_needs: Mapped[dict] = mapped_column(JSONB, default=dict)
    stores_visited: Mapped[list] = mapped_column(JSONB, default=list)
    diagnostic: Mapped[dict] = mapped_column(JSONB, default=dict)
