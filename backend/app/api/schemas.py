"""Schémas Pydantic de l'API (requêtes/réponses)."""

from __future__ import annotations

from datetime import date
from typing import Literal
from decimal import Decimal
from pydantic import BaseModel, Field


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


class MapRequest(BaseModel):
    raw_text: str
    canonical_ingredient_id: str
    confirmed_by: str
