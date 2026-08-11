"""Snapshot du problème d'optimisation.

Les services (validation, scoring, préfiltrage — et le solveur à l'étape 4)
opèrent sur ces dataclasses **pures**, pas sur la session : la logique se
teste sans base, et le chargeur ``load_problem_data`` est le seul point de
contact avec les dépôts. L'assertion 1 est ainsi évaluée **à l'exécution
contre la base** — les prix chargés sont ceux valides à la date demandée,
qu'ils viennent du seed ou, demain, d'un vrai scraper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    CanonicalIngredient,
    HouseholdProfile,
    PantryStock,
    Price,
    Product,
    Recipe,
    Store,
)


@dataclass(frozen=True)
class IngredientData:
    id: str
    name: str
    unit_kind: str
    base_unit: str
    perishability: Decimal
    salvage_value_cents_per_base_unit: Decimal  # σ_i
    density_g_per_ml: Decimal | None


@dataclass(frozen=True)
class RecipeIngredientData:
    canonical_ingredient_id: str
    qty_fixed_per_batch_base_unit: Decimal      # â^fixe_ir
    qty_marginal_per_serving_base_unit: Decimal  # â^marg_ir


@dataclass(frozen=True)
class RecipeData:
    id: str
    name: str
    #: Regroupe les variantes d'échelle du même plat (D16) — l'exclusion
    #: mutuelle du solveur et la pénalité de répétition en dépendent.
    dish_family_id: str
    original_servings: int                       # π_r
    prep_time_fixed_h: Decimal                   # τ^fixe_r
    prep_time_marginal_h: Decimal                # τ^marg_r
    min_batch_servings: int                      # β_r
    max_batch_servings: int                      # m_r
    tags: dict
    required_equipment: tuple[str, ...]
    diet_flags: tuple[str, ...]
    allergen_flags: tuple[str, ...]
    ingredients: tuple[RecipeIngredientData, ...]


@dataclass(frozen=True)
class StoreData:
    id: int
    external_key: str
    banner: str
    lat: Decimal
    lng: Decimal
    shopping_center_id: str | None


@dataclass(frozen=True)
class ProductData:
    id: int
    external_key: str
    canonical_ingredient_id: str
    package_qty_in_base_unit: Decimal            # v_p
    tax_rate: Decimal                            # t_p


@dataclass(frozen=True)
class PriceData:
    product_id: int
    store_id: int
    price_cents_cad: int                         # c_ps
    is_promo: bool
    #: Référence honnête pour les économies affichées (pilote,
    #: docs/product-pilot.md) — None si jamais annoncé au régulier.
    regular_price_cents_cad: int | None


@dataclass(frozen=True)
class ProfileData:
    id: str
    home_lat: Decimal
    home_lng: Decimal
    time_value_cents_per_hour: int               # κ
    meals_per_horizon: int                       # n_repas
    demand_slack_epsilon: Decimal                # ε (D9)
    max_store_visits: int                        # K
    min_distinct_recipes: int                    # R_min
    max_share_per_recipe: Decimal                # α
    diet_flags: tuple[str, ...]
    allergen_flags: tuple[str, ...]
    taste_preferences: dict
    available_equipment: tuple[str, ...]
    max_prep_time_per_meal_h: Decimal
    appetite_coefficients: tuple[Decimal, ...]   # ρ_h


@dataclass(frozen=True)
class ProblemData:
    on_date: date
    profile: ProfileData
    ingredients: dict[str, IngredientData]
    recipes: tuple[RecipeData, ...]
    stores: tuple[StoreData, ...]
    products: tuple[ProductData, ...]
    prices: tuple[PriceData, ...]                # valides à on_date uniquement
    pantry: dict[str, Decimal] = field(default_factory=dict)  # g_i


def load_problem_data(
    session: Session, profile_id: str, on_date: date
) -> ProblemData:
    profile = session.get(HouseholdProfile, profile_id)
    if profile is None:
        raise LookupError(f"household_profile '{profile_id}' introuvable")

    ingredients = {
        i.id: IngredientData(
            id=i.id, name=i.name, unit_kind=i.unit_kind.value,
            base_unit=i.base_unit, perishability=i.perishability,
            salvage_value_cents_per_base_unit=i.salvage_value_cents_per_base_unit,
            density_g_per_ml=i.density_g_per_ml,
        )
        for i in session.scalars(select(CanonicalIngredient))
    }

    recipes = tuple(
        RecipeData(
            id=r.id, name=r.name, dish_family_id=r.dish_family_id,
            original_servings=r.original_servings,
            prep_time_fixed_h=r.prep_time_fixed_h,
            prep_time_marginal_h=r.prep_time_marginal_h,
            min_batch_servings=r.min_batch_servings,
            max_batch_servings=r.max_batch_servings,
            tags=r.tags, required_equipment=tuple(r.required_equipment),
            diet_flags=tuple(r.diet_flags),
            allergen_flags=tuple(r.allergen_flags),
            ingredients=tuple(
                RecipeIngredientData(
                    canonical_ingredient_id=ri.canonical_ingredient_id,
                    qty_fixed_per_batch_base_unit=ri.qty_fixed_per_batch_base_unit,
                    qty_marginal_per_serving_base_unit=(
                        ri.qty_marginal_per_serving_base_unit
                    ),
                )
                for ri in r.ingredients
            ),
        )
        for r in session.scalars(
            select(Recipe).options(selectinload(Recipe.ingredients))
        )
    )

    stores = tuple(
        StoreData(id=s.id, external_key=s.external_key, banner=s.banner,
                  lat=s.lat, lng=s.lng, shopping_center_id=s.shopping_center_id)
        for s in session.scalars(select(Store))
    )
    products = tuple(
        ProductData(id=p.id, external_key=p.external_key,
                    canonical_ingredient_id=p.canonical_ingredient_id,
                    package_qty_in_base_unit=p.package_qty_in_base_unit,
                    tax_rate=p.tax_rate)
        for p in session.scalars(select(Product))
    )
    prices = tuple(
        PriceData(product_id=pr.product_id, store_id=pr.store_id,
                  price_cents_cad=pr.price_cents_cad, is_promo=pr.is_promo,
                  regular_price_cents_cad=pr.regular_price_cents_cad)
        for pr in session.scalars(
            select(Price).where(
                Price.valid_from <= on_date, Price.valid_to >= on_date
            )
        )
    )
    pantry = {
        ps.canonical_ingredient_id: ps.quantity_base_unit
        for ps in session.scalars(
            select(PantryStock).where(
                PantryStock.household_profile_id == profile_id
            )
        )
    }

    return ProblemData(
        on_date=on_date,
        profile=ProfileData(
            id=profile.id, home_lat=profile.home_lat, home_lng=profile.home_lng,
            time_value_cents_per_hour=profile.time_value_cents_per_hour,
            meals_per_horizon=profile.meals_per_horizon,
            demand_slack_epsilon=profile.demand_slack_epsilon,
            max_store_visits=profile.max_store_visits,
            min_distinct_recipes=profile.min_distinct_recipes,
            max_share_per_recipe=profile.max_share_per_recipe,
            diet_flags=tuple(profile.diet_flags),
            allergen_flags=tuple(profile.allergen_flags),
            taste_preferences=profile.taste_preferences,
            available_equipment=tuple(profile.available_equipment),
            max_prep_time_per_meal_h=profile.max_prep_time_per_meal_h,
            appetite_coefficients=tuple(
                m.appetite_coefficient for m in profile.members
            ),
        ),
        ingredients=ingredients,
        recipes=recipes,
        stores=stores,
        products=products,
        prices=prices,
        pantry=pantry,
    )
