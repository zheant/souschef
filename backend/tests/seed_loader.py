"""Construit un ProblemData directement depuis les JSON d'un répertoire de
seed — permet aux tests du solveur de tourner sans base de données."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.services.dish_family import dish_family_id_of
from app.services.problem_data import (
    IngredientData, PriceData, ProblemData, ProductData, ProfileData,
    RecipeData, RecipeIngredientData, StoreData,
)


def problem_from_seed_dir(seed_dir: str | Path, on_date: date) -> ProblemData:
    seed = Path(seed_dir)
    load = lambda name: json.loads((seed / name).read_text())

    ingredients = {
        i["id"]: IngredientData(
            id=i["id"], name=i["name"], unit_kind=i["unit_kind"],
            base_unit=i["base_unit"],
            perishability=(
                Decimal(str(i["perishability"]))
                if i["perishability"] is not None else None
            ),
            salvage_value_cents_per_base_unit=(
                Decimal(str(i["salvage_value_cents_per_base_unit"]))
                if i["salvage_value_cents_per_base_unit"] is not None else None
            ),
            density_g_per_ml=(
                Decimal(str(i["density_g_per_ml"]))
                if i["density_g_per_ml"] is not None else None
            ),
        )
        for i in load("canonical_ingredients.json")
    }
    recipes = tuple(
        RecipeData(
            id=r["id"], name=r["name"],
            dish_family_id=dish_family_id_of(r["id"]),
            original_servings=r["original_servings"],
            prep_time_fixed_h=Decimal(r["prep_time_fixed_h"]),
            prep_time_marginal_h=Decimal(r["prep_time_marginal_h"]),
            min_batch_servings=r["min_batch_servings"],
            max_batch_servings=r["max_batch_servings"],
            tags=r["tags"], required_equipment=tuple(r["required_equipment"]),
            diet_flags=tuple(r["diet_flags"]),
            allergen_flags=tuple(r["allergen_flags"]),
            ingredients=tuple(
                RecipeIngredientData(
                    canonical_ingredient_id=ri["canonical_ingredient_id"],
                    qty_fixed_per_batch_base_unit=Decimal(
                        ri["qty_fixed_per_batch_base_unit"]
                    ),
                    qty_marginal_per_serving_base_unit=Decimal(
                        ri["qty_marginal_per_serving_base_unit"]
                    ),
                )
                for ri in r["ingredients"]
            ),
        )
        for r in load("recipes.json")
    )
    stores = tuple(
        StoreData(
            id=k + 1, external_key=s["external_key"], banner=s["banner"],
            lat=Decimal(str(s["lat"])), lng=Decimal(str(s["lng"])),
            shopping_center_id=s["shopping_center_id"],
        )
        for k, s in enumerate(load("stores.json"))
    )
    store_id = {s.external_key: s.id for s in stores}
    products = tuple(
        ProductData(
            id=k + 1, external_key=p["external_key"],
            canonical_ingredient_id=p["canonical_ingredient_id"],
            package_qty_in_base_unit=Decimal(str(p["package_qty_in_base_unit"])),
            tax_rate=Decimal(str(p["tax_rate"])),
        )
        for k, p in enumerate(load("products.json"))
    )
    product_id = {p.external_key: p.id for p in products}
    prices = tuple(
        PriceData(
            product_id=product_id[o["product_external_key"]],
            store_id=store_id[o["store_external_key"]],
            price_cents_cad=o["price_cents_cad"],
            is_promo=o["is_promo"],
            regular_price_cents_cad=o.get("regular_price_cents_cad"),
        )
        for o in load("raw_offers.json")
        if date.fromisoformat(o["valid_from"]) <= on_date
        <= date.fromisoformat(o["valid_to"])
    )
    h = load("household.json")
    prof = h["profile"]
    profile = ProfileData(
        id=prof["id"], home_lat=Decimal(str(prof["home_lat"])),
        home_lng=Decimal(str(prof["home_lng"])),
        time_value_cents_per_hour=prof["time_value_cents_per_hour"],
        meals_per_horizon=prof["meals_per_horizon"],
        demand_slack_epsilon=Decimal(str(prof["demand_slack_epsilon"])),
        max_store_visits=prof["max_store_visits"],
        min_distinct_recipes=prof["min_distinct_recipes"],
        max_share_per_recipe=Decimal(str(prof["max_share_per_recipe"])),
        diet_flags=tuple(prof["diet_flags"]),
        allergen_flags=tuple(prof["allergen_flags"]),
        taste_preferences=prof.get("taste_preferences", {}),
        available_equipment=tuple(prof["available_equipment"]),
        max_prep_time_per_meal_h=Decimal(str(prof["max_prep_time_per_meal_h"])),
        appetite_coefficients=tuple(
            Decimal(str(mm["appetite_coefficient"])) for mm in h["members"]
        ),
    )
    staples = frozenset(h["staples"])
    return ProblemData(
        on_date=on_date, profile=profile, ingredients=ingredients,
        recipes=recipes, stores=stores, products=products, prices=prices,
        staples=staples,
    )
