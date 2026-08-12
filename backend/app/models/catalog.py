"""Schéma ``catalog`` — référentiel curé par les développeurs.

Le référentiel pivot est ``canonical_ingredient`` : les recettes ne référencent
jamais du texte libre (docs/spec.md, « Modèle de données »).
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, utcnow

SCHEMA = "catalog"


class UnitKind(str, enum.Enum):
    mass = "mass"      # base_unit = g
    volume = "volume"  # base_unit = ml
    count = "count"    # base_unit = unité


class IngredientCurationAction(str, enum.Enum):
    attach_existing = "attach_existing"
    create_variant = "create_variant"
    exclude = "exclude"


class IngredientFamily(TimestampMixin, Base):
    """Regroupement descriptif pour la curation, sans sémantique solveur."""

    __tablename__ = "ingredient_family"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name_fr: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str | None] = mapped_column(String(120))
    description_fr: Mapped[str | None] = mapped_column(Text)

    ingredients: Mapped[list["CanonicalIngredient"]] = relationship(
        back_populates="family"
    )


class CanonicalIngredient(TimestampMixin, Base):
    __tablename__ = "canonical_ingredient"
    __table_args__ = (
        CheckConstraint(
            "perishability IS NULL OR "
            "(perishability >= 0 AND perishability <= 1)",
            name="perishability_01",
        ),
        CheckConstraint(
            "salvage_value_cents_per_base_unit IS NULL OR "
            "salvage_value_cents_per_base_unit >= 0",
            name="salvage_nonneg",
        ),
        CheckConstraint(
            "density_g_per_ml IS NULL OR density_g_per_ml > 0",
            name="density_positive",
        ),
        Index("ix_canonical_ingredient_family_id", "family_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # slug stable
    family_id: Mapped[str | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.ingredient_family.id")
    )
    name: Mapped[str] = mapped_column(String(120))
    unit_kind: Mapped[UnitKind] = mapped_column(
        Enum(UnitKind, name="unit_kind", schema=SCHEMA)
    )
    #: g pour mass, ml pour volume, "unit" pour count — dénormalisé pour lisibilité,
    #: la cohérence avec unit_kind est validée par l'assertion 3 de la spec.
    base_unit: Mapped[str] = mapped_column(String(8))
    perishability: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    #: σ_i — valeur résiduelle par unité de base, en **cents** (Decimal car
    #: sub-cent par gramme/ml ; jamais de flottant pour l'argent).
    salvage_value_cents_per_base_unit: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 6)
    )
    #: Requis pour toute conversion masse↔volume ; jamais de défaut à 1,0.
    density_g_per_ml: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    recipe_ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        back_populates="ingredient"
    )
    family: Mapped[IngredientFamily | None] = relationship(
        back_populates="ingredients"
    )


class CanonicalIngredientAlias(TimestampMixin, Base):
    """Alias humain approuvé pour un ingrédient canonique.

    Les libellés externes importés restent dans ``staging`` tant qu'ils n'ont
    pas été révisés. Cette table ne contient donc que des alias acceptés.
    L'unicité par langue rend le rapprochement exact déterministe.
    """

    __tablename__ = "canonical_ingredient_alias"
    __table_args__ = (
        UniqueConstraint("language", "normalized_alias"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    canonical_ingredient_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA}.canonical_ingredient.id", ondelete="CASCADE")
    )
    language: Mapped[str] = mapped_column(String(8))
    alias: Mapped[str] = mapped_column(Text)
    normalized_alias: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(32))
    source_version: Mapped[str | None] = mapped_column(String(32))
    confirmed_by: Mapped[str | None] = mapped_column(String(120))


class CanonicalIngredientExternalRef(TimestampMixin, Base):
    """Crosswalk versionné entre le canon Souschef et une source externe."""

    __tablename__ = "canonical_ingredient_external_ref"
    __table_args__ = (
        UniqueConstraint("source", "external_id", "source_version"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    canonical_ingredient_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA}.canonical_ingredient.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(64))
    source_version: Mapped[str] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(Text)


class IngredientCurationEvent(TimestampMixin, Base):
    """Journal append-only des décisions humaines appliquées au catalogue.

    La clé naturelle de la source est copiée plutôt que liée par FK à
    ``staging`` : le catalogue conserve ainsi son audit même si une table
    d'atterrissage est purgée. ``decision_fingerprint`` rend le rejeu d'un
    même manifeste idempotent; une correction produit un nouvel événement.
    """

    __tablename__ = "ingredient_curation_event"
    __table_args__ = (
        CheckConstraint(
            "(action = 'exclude' AND canonical_ingredient_id IS NULL) OR "
            "(action <> 'exclude' AND canonical_ingredient_id IS NOT NULL)",
            name="target_matches_action",
        ),
        UniqueConstraint("decision_fingerprint"),
        Index(
            "ix_ingredient_curation_event_source_key",
            "source",
            "source_version",
            "external_id",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    decision_fingerprint: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(32))
    source_version: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(64))
    source_archive_sha256: Mapped[str] = mapped_column(String(64))
    action: Mapped[IngredientCurationAction] = mapped_column(
        Enum(
            IngredientCurationAction,
            name="ingredient_curation_action",
            schema=SCHEMA,
        )
    )
    canonical_ingredient_id: Mapped[str | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.canonical_ingredient.id")
    )
    reviewer: Mapped[str] = mapped_column(String(120))
    rationale: Mapped[str] = mapped_column(Text)
    decision_payload: Mapped[dict] = mapped_column(JSONB)
    candidate_snapshot: Mapped[dict] = mapped_column(JSONB)
    decided_at: Mapped[datetime] = mapped_column(default=utcnow)


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
