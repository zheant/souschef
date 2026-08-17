"""Modèles SQLAlchemy — quatre schémas PostgreSQL : catalog, market, household, staging."""

from .base import Base
from .catalog import (
    CanonicalIngredient,
    CanonicalIngredientAlias,
    CanonicalIngredientExternalRef,
    IngredientCurationAction,
    IngredientCurationEvent,
    IngredientFamily,
    Recipe,
    RecipeIngredient,
    UnitKind,
)
from .household import HouseholdMember, HouseholdProfile, Staple
from .market import (
    MappingStatus,
    Price,
    PricingConfidence,
    Product,
    ProductMapping,
    SaleMode,
    Store,
)
from .plan import Plan, PlanStatus
from .staging import CnfFoodCandidate, IngredientCandidateStatus, RawOffer

SCHEMAS = ("catalog", "market", "household", "staging")

__all__ = [
    "Base",
    "SCHEMAS",
    "CanonicalIngredient",
    "CanonicalIngredientAlias",
    "CanonicalIngredientExternalRef",
    "IngredientCurationAction",
    "IngredientCurationEvent",
    "IngredientFamily",
    "Recipe",
    "RecipeIngredient",
    "UnitKind",
    "Store",
    "Product",
    "Price",
    "ProductMapping",
    "MappingStatus",
    "SaleMode",
    "PricingConfidence",
    "HouseholdProfile",
    "HouseholdMember",
    "Staple",
    "Plan",
    "PlanStatus",
    "RawOffer",
    "CnfFoodCandidate",
    "IngredientCandidateStatus",
]
