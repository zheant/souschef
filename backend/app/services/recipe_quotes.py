"""Façade SQL du module pur de calcul des prix de recettes."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..models import Price, Product, Recipe, Staple, Store
from .recipe_costing import (
    CostingOffer,
    RecipeCostingModule,
    RecipeNotScalableError,
    RecipeQuote,
)
from .supply_rules import SupplyRule, parse_supply_rules

#: Le fichier de règles est lu par trois appelants (cette façade, le script de
#: devis, le script d'audit). Une seule lecture, partagée, pour qu'ils ne
#: puissent plus en tirer des règles différentes.
_parse_supply_rules = parse_supply_rules

_RULES_FILENAME = "ingredient-procurement-rules.json"


class ProcurementRulesUnavailable(RuntimeError):
    """Les règles d'approvisionnement sont introuvables ou illisibles.

    Nommée, parce que sans elle la panne remontait en `FileNotFoundError` brut
    depuis le fond de la couche services. Le chemin était calculé en remontant
    trois dossiers depuis le fichier source, ce qui donne `/config` une fois le
    paquet installé dans l'image — dossier qui n'y existe pas. La route entière
    répondait 500 au premier appel, dans la pile livrée seulement.
    """


def rules_path() -> Path:
    return Path(settings.config_dir) / _RULES_FILENAME


def quote_recipes(
    session: Session,
    on_date: date,
    *,
    recipe_id: str | None = None,
    servings: int | None = None,
    store_external_keys: tuple[str, ...] = (),
) -> tuple[RecipeQuote, ...]:
    recipe_stmt = select(Recipe).options(selectinload(Recipe.ingredients))
    if recipe_id is not None:
        recipe_stmt = recipe_stmt.where(Recipe.id == recipe_id)
    recipes = tuple(session.scalars(recipe_stmt.order_by(Recipe.id)))
    if recipe_id is not None and not recipes:
        raise LookupError(f"Recette '{recipe_id}' introuvable.")

    price_stmt = (
        select(Product, Price, Store)
        .join(Price, Price.product_id == Product.id)
        .join(Store, Store.id == Price.store_id)
        .where(Price.valid_from <= on_date, Price.valid_to >= on_date)
    )
    if store_external_keys:
        price_stmt = price_stmt.where(Store.external_key.in_(store_external_keys))
    # Sans ordre explicite, PostgreSQL n'en garantit aucun: deux appels
    # identiques pouvaient citer deux produits différents à prix unitaire égal.
    price_stmt = price_stmt.order_by(Store.external_key, Product.external_key)
    offers = tuple(
        CostingOffer(
            product_external_key=product.external_key,
            canonical_ingredient_id=product.canonical_ingredient_id,
            store_external_key=store.external_key,
            quantity_in_base_unit=product.package_qty_in_base_unit,
            price_cents_cad=price.price_cents_cad,
            tax_rate=product.tax_rate,
            regular_price_cents_cad=price.regular_price_cents_cad,
            is_promo=price.is_promo,
            sale_mode=product.sale_mode.value,
            purchase_increment_in_base_unit=(
                product.purchase_increment_in_base_unit
            ),
            valid_from=price.valid_from.isoformat(),
            valid_to=price.valid_to.isoformat(),
            confidence=max(
                (price.pricing_confidence.value, product.quantity_confidence.value),
                key={
                    "exact": 0,
                    "audited_conversion": 1,
                    "estimated": 2,
                    "incomplete": 3,
                }.__getitem__,
            ),
        )
        for product, price, store in session.execute(price_stmt)
    )
    return tuple(
        RecipeCostingModule.quote_all(
            recipes,
            offers,
            servings=servings,
            stores=store_external_keys or None,
            supply_rules=_load_supply_rules(),
            staples=_household_staples(session),
        )
    )


def _household_staples(session: Session) -> tuple[str, ...]:
    """Essentiels déclarés par le ménage, lus là où ils vivent déjà.

    Le concept existait côté solveur (`household.staple`, `enable_staples`) mais
    le calcul de prix ne le lisait pas : seule l'eau était déclarée essentielle
    dans le fichier de règles, et tout le reste se rachetait en entier. Les
    recopier à la main dans ce fichier aurait créé une deuxième source de
    vérité, vouée à diverger de la première.
    """
    return tuple(
        session.scalars(
            select(Staple.canonical_ingredient_id)
            .where(Staple.household_profile_id == settings.household_profile_id)
            .order_by(Staple.canonical_ingredient_id)
        )
    )


@lru_cache(maxsize=None)
def _load_supply_rules_cached(path: str) -> tuple[SupplyRule, ...]:
    """Les règles sont relues une fois, pas à chaque requête HTTP."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ProcurementRulesUnavailable(
            f"Règles d'approvisionnement introuvables: {path}. "
            "Vérifier MENU_CONFIG_DIR et la présence du dossier de configuration."
        ) from error
    except json.JSONDecodeError as error:
        raise ProcurementRulesUnavailable(
            f"Règles d'approvisionnement illisibles: {path} ({error})."
        ) from error
    return _parse_supply_rules(payload)


def _load_supply_rules() -> tuple[SupplyRule, ...]:
    return _load_supply_rules_cached(str(rules_path()))
