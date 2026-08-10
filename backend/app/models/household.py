"""Schéma ``household`` — profil unique en v1 (aucune authentification).

Préséance des paramètres (docs/spec.md) : ``household_profile`` est la source
de vérité ; les champs homonymes de ``SolverConfig`` sont des surcharges
optionnelles résolues par une fonction unique (implémentée à l'étape 4).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

SCHEMA = "household"
CATALOG = "catalog"


class HouseholdProfile(TimestampMixin, Base):
    __tablename__ = "household_profile"
    __table_args__ = (
        CheckConstraint("meals_per_horizon > 0", name="meals_positive"),
        CheckConstraint("max_store_visits >= 1", name="k_ge_1"),
        CheckConstraint("min_distinct_recipes >= 1", name="rmin_ge_1"),
        CheckConstraint(
            "max_share_per_recipe > 0 AND max_share_per_recipe <= 1",
            name="alpha_01",
        ),
        CheckConstraint("time_value_cents_per_hour >= 0", name="kappa_nonneg"),
        CheckConstraint(
            "demand_slack_epsilon >= 0 AND demand_slack_epsilon < 1",
            name="epsilon_range",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    home_lat: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    home_lng: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    #: κ — valeur du temps, en cents CAD par heure.
    time_value_cents_per_hour: Mapped[int]
    #: n_repas — nombre de repas sur l'horizon (pool indifférencié de portions).
    meals_per_horizon: Mapped[int]
    #: ε — marge de la demande (décision du point de contrôle de l'étape 2,
    #: docs/deviations.md D9) : ⌈D⌉ ≤ Σx_r ≤ ⌈D(1+ε)⌉. Surchargeable par
    #: SolverConfig. La borne basse garantit que le ménage mange, la haute
    #: empêche la surproduction, la marge laisse le solveur ajuster les
    #: portions aux formats d'emballage.
    demand_slack_epsilon: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    max_store_visits: Mapped[int]        # K       (surchargeable)
    min_distinct_recipes: Mapped[int]    # R_min   (surchargeable)
    max_share_per_recipe: Mapped[Decimal] = mapped_column(Numeric(4, 3))  # α (surch.)
    diet_flags: Mapped[list] = mapped_column(JSONB, default=list)
    allergen_flags: Mapped[list] = mapped_column(JSONB, default=list)
    #: Préférences gustatives déclarées, matière première du scoring
    #: d'appétence : {"liked_tags": [...], "disliked_tags": [...]}
    #: (ajout au schéma consigné en D10).
    taste_preferences: Mapped[dict] = mapped_column(JSONB, default=dict)
    available_equipment: Mapped[list] = mapped_column(JSONB, default=list)
    #: Filtre dur du préfiltrage, en heures par repas.
    max_prep_time_per_meal_h: Mapped[Decimal] = mapped_column(Numeric(6, 3))

    members: Mapped[list["HouseholdMember"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class HouseholdMember(TimestampMixin, Base):
    __tablename__ = "household_member"
    __table_args__ = (
        UniqueConstraint("household_profile_id", "name"),
        CheckConstraint("appetite_coefficient > 0", name="rho_positive"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    household_profile_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA}.household_profile.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    #: ρ_h — coefficient d'appétit du membre.
    appetite_coefficient: Mapped[Decimal] = mapped_column(Numeric(5, 3))

    profile: Mapped[HouseholdProfile] = relationship(back_populates="members")


class PantryStock(TimestampMixin, Base):
    """g_i — stock du garde-manger, reporté d'une exécution à l'autre
    (le ``commit`` d'un plan y reversera les surplus w_i, étape 5)."""

    __tablename__ = "pantry_stock"
    __table_args__ = (
        UniqueConstraint("household_profile_id", "canonical_ingredient_id"),
        CheckConstraint("quantity_base_unit >= 0", name="qty_nonneg"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    household_profile_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA}.household_profile.id", ondelete="CASCADE")
    )
    canonical_ingredient_id: Mapped[str] = mapped_column(
        ForeignKey(f"{CATALOG}.canonical_ingredient.id")
    )
    #: Quantité dans la base_unit de l'ingrédient canonique.
    quantity_base_unit: Mapped[Decimal] = mapped_column(Numeric(12, 3))
