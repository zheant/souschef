"""Schéma ``household`` — profil unique en v1 (aucune authentification).

Préséance des paramètres (docs/spec.md) : ``household_profile`` est la source
de vérité ; les champs homonymes de ``SolverConfig`` sont des surcharges
optionnelles résolues par une fonction unique (implémentée à l'étape 4).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import (
    CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint,
)
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
        CheckConstraint(
            "appetence_u_min_dollars IS NULL OR appetence_u_min_dollars >= 0",
            name="u_min_nonneg",
        ),
        CheckConstraint(
            "min_protein_g_per_serving IS NULL OR min_protein_g_per_serving >= 0",
            name="min_protein_nonneg",
        ),
        CheckConstraint(
            "max_distinct_recipes IS NULL OR max_distinct_recipes >= 1",
            name="r_max_at_least_one",
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
    #: U_min — plancher d'appétence du plan, en dollars-équivalents. `NULL` :
    #: aucun plancher, l'appétence reste un crédit dans l'objectif.
    #:
    #: Sans plancher, le solveur minimise `achats − Σu_r·x_r` : toute recette
    #: dont le coût par portion est sous son u_r a un apport net négatif, donc
    #: la moins chère gagne systématiquement. Mesuré sur `seed/main` : les six
    #: recettes retenues étaient exactement les six apports nets les plus bas,
    #: et « Tacos au bœuf » — deuxième meilleure appétence du catalogue —
    #: n'était jamais choisi. Un plancher inverse la question : minimiser le
    #: coût *sous* une appétence totale exigée. Surchargeable par SolverConfig,
    #: résolu par `services/params.py` comme K, R_min, α et ε.
    appetence_u_min_dollars: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    #: Plancher de protéines : grammes par portion, en **moyenne sur le menu**,
    #: et non par plat — c'est la semaine qui doit être protéinée, et un plat
    #: léger reste servable s'il est compensé. `None` : aucun plancher, et non
    #: zéro, qui serait une contrainte satisfaite d'avance que le solveur
    #: construirait pour rien.
    #:
    #: Le pendant du plancher d'appétence, dans l'unité que le ménage surveille :
    #: l'appétence dit « quel menu me plaît », les protéines disent « de quoi il
    #: est fait ». Surchargeable par SolverConfig, résolu par
    #: `services/params.py` comme K, R_min, α, ε et U_min.
    min_protein_g_per_serving: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    #: R_max — nombre maximal de plats distincts au menu. `None` : aucun
    #: plafond. Le pendant de R_min, mais il s'applique **même sans le drapeau
    #: de diversité** : R_min sert à forcer la variété quand on l'étudie, R_max
    #: à borner ce qu'un ménage accepte de cuisiner dans une semaine.
    max_distinct_recipes: Mapped[int | None] = mapped_column(nullable=True)

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


class Staple(TimestampMixin, Base):
    """Un ingrédient que ce ménage est supposé toujours avoir sous la main
    (pilote, docs/product-pilot.md — remplace le garde-manger à quantité
    suivie, retiré : l'input utilisateur qu'il exigeait divergeait
    inévitablement du stock réel). Pure appartenance — aucune quantité,
    aucune priorité. Au solveur, un essentiel n'est jamais gratuit : il est
    acheté comme n'importe quel ingrédient, seulement évalué dans
    l'objectif au prix historique le plus bas de la dernière année
    (``services/pricing.py::historical_min_price_per_base_unit``), ce qui
    biaise le *choix* de recettes sans jamais fausser le montant réel
    affiché."""

    __tablename__ = "staple"
    __table_args__ = (
        UniqueConstraint("household_profile_id", "canonical_ingredient_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    household_profile_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA}.household_profile.id", ondelete="CASCADE")
    )
    canonical_ingredient_id: Mapped[str] = mapped_column(
        ForeignKey(f"{CATALOG}.canonical_ingredient.id")
    )
