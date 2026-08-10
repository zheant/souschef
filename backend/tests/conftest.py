"""Fabriques de données pures pour les tests de services (sans base)."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.dish_family import dish_family_id_of
from app.services.problem_data import (
    IngredientData, PriceData, ProblemData, ProductData, ProfileData,
    RecipeData, RecipeIngredientData, StoreData,
)


def make_ingredient(iid="riz", kind="mass", base_unit="g", sigma="0.10",
                    density=None):
    return IngredientData(
        id=iid, name=iid, unit_kind=kind, base_unit=base_unit,
        perishability=Decimal("0.1"),
        salvage_value_cents_per_base_unit=Decimal(sigma),
        density_g_per_ml=Decimal(density) if density else None,
    )


def make_recipe(rid="r1", beta=1, m=8, tags=None, allergens=(), diets=(),
                equipment=(), tfix="0.2", tmarg="0.05",
                ingredients=(("riz", "0", "80"),), dish_family_id=None):
    return RecipeData(
        id=rid, name=rid,
        dish_family_id=dish_family_id or dish_family_id_of(rid),
        original_servings=2,
        prep_time_fixed_h=Decimal(tfix), prep_time_marginal_h=Decimal(tmarg),
        min_batch_servings=beta, max_batch_servings=m,
        tags=tags or {}, required_equipment=tuple(equipment),
        diet_flags=tuple(diets), allergen_flags=tuple(allergens),
        ingredients=tuple(
            RecipeIngredientData(i, Decimal(f), Decimal(g))
            for (i, f, g) in ingredients
        ),
    )


def make_profile(rho=("1.0", "1.0", "0.6"), meals=14, epsilon="0.10",
                 r_min=4, alpha="0.3", liked=(), disliked=(), allergens=(),
                 diets=(), equipment=("four",), tmax="1.5", k=2):
    return ProfileData(
        id="default", home_lat=Decimal("45.5"), home_lng=Decimal("-73.6"),
        time_value_cents_per_hour=1500, meals_per_horizon=meals,
        demand_slack_epsilon=Decimal(epsilon), max_store_visits=k,
        min_distinct_recipes=r_min, max_share_per_recipe=Decimal(alpha),
        diet_flags=tuple(diets), allergen_flags=tuple(allergens),
        taste_preferences={"liked_tags": list(liked),
                           "disliked_tags": list(disliked)},
        available_equipment=tuple(equipment),
        max_prep_time_per_meal_h=Decimal(tmax),
        appetite_coefficients=tuple(Decimal(r) for r in rho),
    )


def make_problem(profile=None, ingredients=None, recipes=None, prices=None,
                 products=None, stores=None, on=date(2026, 8, 10)):
    ingredients = ingredients or [make_ingredient()]
    products = products if products is not None else [
        ProductData(id=1, external_key="riz_1kg", canonical_ingredient_id="riz",
                    package_qty_in_base_unit=Decimal("1000"),
                    tax_rate=Decimal("0")),
    ]
    prices = prices if prices is not None else [
        PriceData(product_id=1, store_id=1, price_cents_cad=300, is_promo=False),
    ]
    stores = stores if stores is not None else [
        StoreData(id=1, external_key="s1", banner="S1", lat=Decimal("45.5"),
                  lng=Decimal("-73.6"), shopping_center_id=None),
    ]
    return ProblemData(
        on_date=on, profile=profile or make_profile(),
        ingredients={i.id: i for i in ingredients},
        recipes=tuple(recipes or [make_recipe()]),
        stores=tuple(stores), products=tuple(products), prices=tuple(prices),
    )


@pytest.fixture
def default_problem():
    return make_problem()
