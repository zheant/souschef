"""DTO des ports d'acquisition (Pydantic v2).

Ces types sont le CONTRAT entre l'extérieur (scraper, catalogue de recettes) et
la couche d'ingestion : un vrai scraper devra produire exactement ces objets.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RawOfferDTO(BaseModel):
    """Offre brute telle que vue dans une circulaire, avant toute normalisation.

    ``raw_text`` est le libellé source (celui que ``product_mapping`` devra
    résoudre) ; ``product_external_key`` est présent quand la source connaît
    déjà le produit (cas de l'adaptateur JSON v1).
    """

    model_config = ConfigDict(frozen=True)

    store_external_key: str
    week: str = Field(pattern=r"^\d{4}-W\d{2}$")
    raw_text: str
    product_external_key: str | None = None
    price_cents_cad: int = Field(ge=0)
    regular_price_cents_cad: int | None = Field(default=None, ge=0)
    is_promo: bool = False
    valid_from: str  # ISO date
    valid_to: str    # ISO date


class RecipeIngredientDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical_ingredient_id: str
    qty_fixed_per_batch_base_unit: Decimal = Field(ge=0)
    qty_marginal_per_serving_base_unit: Decimal = Field(ge=0)
    substitutable: bool = False  # stocké tel quel ; jamais lu par la logique v1


class RecipeDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    original_servings: int = Field(ge=1)
    prep_time_fixed_h: Decimal = Field(ge=0)
    prep_time_marginal_h: Decimal = Field(ge=0)
    min_batch_servings: int = Field(ge=1)   # β_r ≥ 1 (assertion 2)
    max_batch_servings: int = Field(ge=1)   # m_r ≥ β_r vérifié en aval
    tags: dict = Field(default_factory=dict)
    required_equipment: list[str] = Field(default_factory=list)
    diet_flags: list[str] = Field(default_factory=list)
    allergen_flags: list[str] = Field(default_factory=list)
    ingredients: tuple[RecipeIngredientDTO, ...] = ()
