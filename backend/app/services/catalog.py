"""``CatalogModule`` — recherche de recettes et liste des magasins.

Données de référence en lecture seule ; même convention que
``services/planning.py``/``services/household.py`` (session explicite, pas
d'ouverture interne — voir la docstring de ``planning.py``).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import Recipe, RecipeIngredient, Store


class RecipeNotFound(LookupError):
    """Aucune recette avec cet id (l'API traduit en 404)."""


@dataclass(frozen=True)
class RecipeQuery:
    q: str | None = None
    diet: str | None = None
    tag_cuisine: str | None = None
    limit: int = 20
    offset: int = 0


@dataclass(frozen=True)
class RecipeSummary:
    id: str
    name: str
    original_servings: int
    prep_time_fixed_h: str
    prep_time_marginal_h: str
    min_batch_servings: int
    max_batch_servings: int
    tags: dict
    diet_flags: list
    allergen_flags: list


@dataclass(frozen=True)
class RecipePage:
    total: int
    limit: int
    offset: int
    items: tuple[RecipeSummary, ...]


@dataclass(frozen=True)
class RecipeIngredientLine:
    canonical_ingredient_id: str
    name: str


@dataclass(frozen=True)
class StoreView:
    external_key: str
    banner: str
    address: str
    lat: float
    lng: float
    shopping_center_id: str | None


def search_recipes(session: Session, query: RecipeQuery) -> RecipePage:
    stmt = select(Recipe).order_by(Recipe.id)
    if query.q:
        stmt = stmt.where(Recipe.name.ilike(f"%{query.q}%"))
    if query.diet:
        stmt = stmt.where(Recipe.diet_flags.contains([query.diet]))
    if query.tag_cuisine:
        stmt = stmt.where(Recipe.tags["cuisine"].astext == query.tag_cuisine)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.scalars(stmt.limit(query.limit).offset(query.offset)).all()
    return RecipePage(
        total=total, limit=query.limit, offset=query.offset,
        items=tuple(
            RecipeSummary(
                id=r.id, name=r.name,
                original_servings=r.original_servings,
                prep_time_fixed_h=str(r.prep_time_fixed_h),
                prep_time_marginal_h=str(r.prep_time_marginal_h),
                min_batch_servings=r.min_batch_servings,
                max_batch_servings=r.max_batch_servings,
                tags=r.tags, diet_flags=r.diet_flags,
                allergen_flags=r.allergen_flags,
            )
            for r in rows
        ),
    )


def get_recipe_ingredients(
    session: Session, recipe_id: str
) -> tuple[RecipeIngredientLine, ...]:
    """Ingrédients d'une seule recette (détail recette, pilote,
    docs/product-pilot.md) — ``Recipe.ingredients`` existe en base depuis
    l'étape 1 mais n'était exposé par aucune route jusqu'ici."""
    recipe = session.get(
        Recipe, recipe_id,
        options=[selectinload(Recipe.ingredients).selectinload(RecipeIngredient.ingredient)],
    )
    if recipe is None:
        raise RecipeNotFound(f"Recette '{recipe_id}' introuvable.")
    return tuple(
        RecipeIngredientLine(
            canonical_ingredient_id=ri.canonical_ingredient_id,
            name=ri.ingredient.name,
        )
        for ri in recipe.ingredients
    )


def list_stores(session: Session) -> tuple[StoreView, ...]:
    return tuple(
        StoreView(
            external_key=s.external_key, banner=s.banner,
            address=s.address, lat=float(s.lat), lng=float(s.lng),
            shopping_center_id=s.shopping_center_id,
        )
        for s in session.scalars(select(Store).order_by(Store.external_key))
    )
