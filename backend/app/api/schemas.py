"""Schémas Pydantic de l'API (requêtes/réponses)."""

from __future__ import annotations

from datetime import date
from typing import Literal
from decimal import Decimal
from pydantic import BaseModel, Field, model_validator


class MemberOut(BaseModel):
    name: str
    appetite_coefficient: float


class HouseholdOut(BaseModel):
    id: str
    home_lat: float
    home_lng: float
    time_value_cents_per_hour: int
    meals_per_horizon: int
    demand_slack_epsilon: Decimal
    max_store_visits: int
    min_distinct_recipes: int
    max_share_per_recipe: float
    diet_flags: list[str]
    allergen_flags: list[str]
    taste_preferences: dict
    available_equipment: list[str]
    max_prep_time_per_meal_h: float
    members: list[MemberOut]
    demand: dict  # D exact + bornes (D9)


class HouseholdUpdate(BaseModel):
    """Mise à jour partielle du profil ; members (si fourni) remplace la liste."""

    home_lat: float | None = None
    home_lng: float | None = None
    time_value_cents_per_hour: int | None = Field(default=None, ge=0)
    meals_per_horizon: int | None = Field(default=None, gt=0)
    demand_slack_epsilon: Decimal | None = Field(default=None, ge=0, lt=1)
    max_store_visits: int | None = Field(default=None, ge=1)
    min_distinct_recipes: int | None = Field(default=None, ge=1)
    max_share_per_recipe: float | None = Field(default=None, gt=0, le=1)
    diet_flags: list[str] | None = None
    allergen_flags: list[str] | None = None
    taste_preferences: dict | None = None
    available_equipment: list[str] | None = None
    max_prep_time_per_meal_h: float | None = Field(default=None, gt=0)
    members: list[MemberOut] | None = None


class PantryLine(BaseModel):
    canonical_ingredient_id: str
    quantity_base_unit: float = Field(ge=0)


class PantryUpdate(BaseModel):
    """Upsert des lignes fournies ; une quantité 0 met la ligne à zéro."""

    lines: list[PantryLine]


class SetPantryPriorityRequest(BaseModel):
    """Périssables prioritaires ou obligatoires (pilote,
    docs/product-pilot.md) — endpoint séparé de ``PUT /api/pantry`` à
    dessein (voir ``services/household.py::update_pantry``)."""

    priority: Literal["normal", "use_soon", "must_use"]


class PlanRequest(BaseModel):
    """SolverConfig partielle — tout champ absent prend le défaut de
    développement (spec)."""

    config: dict = Field(default_factory=dict)
    on_date: date | None = None


class MenuLine(BaseModel):
    recipe_id: str
    name: str
    servings: int
    prep_time_h: str
    attributed_cost_cents_cad: str


class PlanOut(BaseModel):
    id: int
    status: Literal["proposed", "committed"]
    solver_status: str
    on_date: date
    menu: list[MenuLine]
    grocery_list_by_store: list[dict]
    stores_visited: list[str]
    diagnostic: dict


class PantryPromptLineOut(BaseModel):
    """Confirmation du garde-manger en deux temps (pilote,
    docs/product-pilot.md) : ligne d'ingrédient priorisée pour un plan
    précis, pas un inventaire exhaustif."""

    canonical_ingredient_id: str
    name: str
    unit_kind: str
    base_unit: str
    needed_quantity_base_unit: str
    perishability: str
    estimated_cost_cents: str


class ReoptimizeRequest(BaseModel):
    """Verrouillage/remplacement de recette (pilote, docs/product-pilot.md).
    ``locked_recipe_ids`` doivent appartenir au plan visé ; leurs portions
    sont fixées exactement, jamais changées silencieusement.
    ``excluded_recipe_ids`` sont écartées (et leurs variantes d'échelle
    sœurs, D16) de la réoptimisation."""

    config: dict = Field(default_factory=dict)
    locked_recipe_ids: list[str] = Field(default_factory=list)
    excluded_recipe_ids: list[str] = Field(default_factory=list)


class MenuChangeOut(BaseModel):
    added: list[str]
    removed: list[str]
    cost_delta_cents: str


class ReoptimizeOut(BaseModel):
    plan: PlanOut
    #: None si le nouveau plan est infaisable — voir plan.diagnostic.
    changes: MenuChangeOut | None


class NewProductIn(BaseModel):
    """Spécification d'un nouveau produit à créer (D18) — saisie manuelle,
    aucune extraction automatique depuis ``raw_text``."""

    canonical_ingredient_id: str
    brand: str
    package_qty_in_base_unit: Decimal = Field(gt=0)
    package_unit: str
    tax_rate: Decimal = Field(ge=0, lt=1)


class MapRequest(BaseModel):
    """Confirmation d'une offre non résolue : attacher un produit existant
    (``product_id``) ou en créer un nouveau (``new_product``) — exactement
    l'un des deux. La clé de résolution est (magasin, texte brut), pas le
    texte brut seul (D18) : un même libellé désigne des produits différents
    d'une bannière à l'autre."""

    store_external_key: str
    raw_text: str
    confirmed_by: str
    product_id: int | None = None
    new_product: NewProductIn | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "MapRequest":
        if (self.product_id is None) == (self.new_product is None):
            raise ValueError(
                "Fournir exactement un de product_id ou new_product."
            )
        return self
