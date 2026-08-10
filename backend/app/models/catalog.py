"""Schéma ``catalog`` — référentiel curé par les développeurs.

Le référentiel pivot est ``canonical_ingredient`` : les recettes ne référencent
jamais du texte libre (docs/spec.md, « Modèle de données »).
"""

from __future__ import annotations

import enum
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

SCHEMA = "catalog"


class UnitKind(str, enum.Enum):
    mass = "mass"      # base_unit = g
    volume = "volume"  # base_unit = ml
    count = "count"    # base_unit = unité


class CanonicalIngredient(TimestampMixin, Base):
    __tablename__ = "canonical_ingredient"
    __table_args__ = (
        CheckConstraint(
            "perishability >= 0 AND perishability <= 1", name="perishability_01"
        ),
        CheckConstraint(
            "salvage_value_cents_per_base_unit >= 0", name="salvage_nonneg"
        ),
        CheckConstraint(
            "density_g_per_ml IS NULL OR density_g_per_ml > 0",
            name="density_positive",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # slug stable
    name: Mapped[str] = mapped_column(String(120))
    unit_kind: Mapped[UnitKind] = mapped_column(
        Enum(UnitKind, name="unit_kind", schema=SCHEMA)
    )
    #: g pour mass, ml pour volume, "unit" pour count — dénormalisé pour lisibilité,
    #: la cohérence avec unit_kind est validée par l'assertion 3 de la spec.
    base_unit: Mapped[str] = mapped_column(String(8))
    perishability: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    #: σ_i — valeur résiduelle par unité de base, en **cents** (Decimal car
    #: sub-cent par gramme/ml ; jamais de flottant pour l'argent).
    salvage_value_cents_per_base_unit: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    #: Requis pour toute conversion masse↔volume ; jamais de défaut à 1,0.
    density_g_per_ml: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    recipe_ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        back_populates="ingredient"
    )


class Recipe(TimestampMixin, Base):
    __tablename__ = "recipe"
    __table_args__ = (
        # Assertion 2 de la spec, portée aussi par la base : β_r ≥ 1 et m_r ≥ β_r.
        CheckConstraint("min_batch_servings >= 1", name="beta_ge_1"),
        CheckConstraint(
            "max_batch_servings >= min_batch_servings", name="m_ge_beta"
        ),
        CheckConstraint("original_servings >= 1", name="pi_ge_1"),
        CheckConstraint(
            "prep_time_fixed_h >= 0 AND prep_time_marginal_h >= 0",
            name="prep_time_nonneg",
        ),
        Index("ix_recipe_dish_family_id", "dish_family_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # slug stable
    name: Mapped[str] = mapped_column(String(160))
    #: Regroupe les variantes d'échelle du même plat (D16, docs/deviations.md) :
    #: dérivé de la convention <id>/<id>_familial via
    #: services.dish_family.dish_family_id_of, jamais lu par le solveur pour
    #: autre chose que l'exclusion mutuelle des variantes.
    dish_family_id: Mapped[str] = mapped_column(String(64), nullable=False)
    original_servings: Mapped[int]                                  # π_r
    prep_time_fixed_h: Mapped[Decimal] = mapped_column(Numeric(6, 3))    # τ^fixe_r
    prep_time_marginal_h: Mapped[Decimal] = mapped_column(Numeric(6, 3))  # τ^marg_r
    min_batch_servings: Mapped[int]                                 # β_r
    max_batch_servings: Mapped[int]                                 # m_r
    tags: Mapped[dict] = mapped_column(JSONB, default=dict)
    required_equipment: Mapped[list] = mapped_column(JSONB, default=list)
    diet_flags: Mapped[list] = mapped_column(JSONB, default=list)
    allergen_flags: Mapped[list] = mapped_column(JSONB, default=list)

    ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredient"
    __table_args__ = (
        UniqueConstraint("recipe_id", "canonical_ingredient_id"),
        CheckConstraint(
            "qty_fixed_per_batch_base_unit >= 0"
            " AND qty_marginal_per_serving_base_unit >= 0",
            name="qty_nonneg",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    recipe_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA}.recipe.id", ondelete="CASCADE")
    )
    canonical_ingredient_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA}.canonical_ingredient.id")
    )
    #: â^fixe_ir — quantité par lot, dans la base_unit de l'ingrédient (ne scale pas).
    qty_fixed_per_batch_base_unit: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    #: â^marg_ir — quantité par portion, dans la base_unit de l'ingrédient.
    qty_marginal_per_serving_base_unit: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    #: RÉSERVÉ à une version ultérieure (docs/spec.md) : présent dans le schéma
    #: pour éviter une migration, mais AUCUNE logique v1 ne doit le lire —
    #: ni solveur, ni préfiltrage, ni API.
    substitutable: Mapped[bool] = mapped_column(default=False)

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")
    ingredient: Mapped[CanonicalIngredient] = relationship(
        back_populates="recipe_ingredients"
    )
