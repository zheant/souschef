"""Modèles SQLAlchemy — quatre schémas PostgreSQL : catalog, market, household, staging."""

from .base import Base
from .catalog import CanonicalIngredient, Recipe, RecipeIngredient, UnitKind
from .household import HouseholdMember, HouseholdProfile, PantryStock
from .market import MappingStatus, Price, Product, ProductMapping, Store
from .plan import Plan, PlanStatus
from .staging import RawOffer

SCHEMAS = ("catalog", "market", "household", "staging")

__all__ = [
    "Base",
    "SCHEMAS",
    "CanonicalIngredient",
    "Recipe",
    "RecipeIngredient",
    "UnitKind",
    "Store",
    "Product",
    "Price",
    "ProductMapping",
    "MappingStatus",
    "HouseholdProfile",
    "HouseholdMember",
    "PantryStock",
    "Plan",
    "PlanStatus",
    "RawOffer",
]
