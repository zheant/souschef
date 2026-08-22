"""``CatalogModule`` — recettes et magasins : lecture, création, suppression.

La lecture est de la donnée de référence. L'écriture est arrivée avec la gestion
des recettes depuis l'application (D44) : ajouter et retirer une recette. Elle
porte deux refus qui ne sont pas décoratifs — une recette dont aucune quantité
n'est demandée serait servie gratuitement par le solveur (D25), et une recette
citée par un plan ne peut pas disparaître sans son plan, sinon l'écran de menu
échange un faux menu contre une 500 (le piège que
`scripts/purge_demo_recipes.py` documente).

Même convention que
``services/planning.py``/``services/household.py`` (session explicite, pas
d'ouverture interne — voir la docstring de ``planning.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from ..ingestion.ingredient_curation import normalize_label
from ..models import (
    CanonicalIngredient,
    Plan,
    Price,
    Recipe,
    RecipeIngredient,
    Store,
)
from .dish_family import dish_family_id_of


class RecipeNotFound(LookupError):
    """Aucune recette avec cet id (l'API traduit en 404)."""


class RecipeDraftInvalid(ValueError):
    """La recette proposée ne peut pas entrer au catalogue, et le refus dit
    pourquoi (l'API traduit en 422)."""


class RecipeInUse(RuntimeError):
    """Un plan cite cette recette. Le refus liste les plans (l'API traduit en
    409) : le sort d'un plan est une décision, pas un effet de bord."""


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


@dataclass(frozen=True)
class PriceCoverage:
    """Fenêtre de dates réellement couverte par `market.price`.

    Le solveur n'accepte que les prix dont la fenêtre de validité contient
    `on_date` (`problem_data.py`). Hors couverture, aucune recette ne survit
    au préfiltrage — l'échec est correct mais l'appelant ne pouvait pas le
    prévoir, faute de savoir ce qui est chargé. `None` : aucun prix en base.
    """

    earliest: date | None
    latest: date | None


def price_coverage(session: Session) -> PriceCoverage:
    earliest, latest = session.execute(
        select(func.min(Price.valid_from), func.max(Price.valid_to))
    ).one()
    return PriceCoverage(earliest=earliest, latest=latest)


@dataclass(frozen=True)
class IngredientOption:
    """Un ingrédient canonique, tel qu'un formulaire le propose."""

    id: str
    name: str
    base_unit: str


def search_ingredients(
    session: Session, q: str | None = None, limit: int = 20
) -> tuple[IngredientOption, ...]:
    """Ingrédients canoniques dont le nom contient `q`.

    Le formulaire de recette en a besoin : une recette cite des ingrédients
    canoniques par identifiant, et personne ne tape `farine_tout_usage` de
    mémoire. L'unité de base voyage avec le nom, parce que c'est elle qui dit en
    quoi la quantité se saisit — 300 **g** de farine, 250 **ml** de lait.
    """
    stmt = select(CanonicalIngredient).order_by(CanonicalIngredient.name)
    if q:
        stmt = stmt.where(CanonicalIngredient.name.ilike(f"%{q}%"))
    return tuple(
        IngredientOption(id=row.id, name=row.name, base_unit=row.base_unit)
        for row in session.scalars(stmt.limit(limit))
    )


def _summary(recipe: Recipe) -> RecipeSummary:
    """La projection d'une recette, écrite une fois.

    La recherche et la création rendent la même chose : deux projections du même
    enregistrement finiraient par diverger d'un champ, et l'écran afficherait
    deux vérités selon le chemin qui l'a servi.
    """
    return RecipeSummary(
        id=recipe.id,
        name=recipe.name,
        original_servings=recipe.original_servings,
        prep_time_fixed_h=str(recipe.prep_time_fixed_h),
        prep_time_marginal_h=str(recipe.prep_time_marginal_h),
        min_batch_servings=recipe.min_batch_servings,
        max_batch_servings=recipe.max_batch_servings,
        tags=recipe.tags,
        diet_flags=recipe.diet_flags,
        allergen_flags=recipe.allergen_flags,
    )


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
        items=tuple(_summary(r) for r in rows),
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


@dataclass(frozen=True)
class RecipeDraft:
    """Une recette proposée depuis l'application.

    Les quantités arrivent en texte, pas en flottant : une quantité d'ingrédient
    est une décimale exacte dans la base, et la faire passer par un `float`
    l'arrondirait sur le chemin.
    """

    name: str
    original_servings: int
    prep_time_fixed_h: str
    prep_time_marginal_h: str
    min_batch_servings: int
    max_batch_servings: int
    ingredients: list[dict]
    tags: dict | None = None
    required_equipment: list | None = None
    diet_flags: list | None = None
    allergen_flags: list | None = None


def create_recipe(session: Session, draft: RecipeDraft) -> RecipeSummary:
    """Ajoute une recette au catalogue, ou refuse en nommant le défaut."""
    name = draft.name.strip()
    if not name:
        raise RecipeDraftInvalid("Une recette sans nom ne se retrouve pas.")
    if not draft.ingredients:
        raise RecipeDraftInvalid("Une recette sans ingrédient n'est pas une recette.")
    if draft.min_batch_servings < 1 or draft.max_batch_servings < draft.min_batch_servings:
        raise RecipeDraftInvalid(
            f"Bornes de lot incohérentes : β = {draft.min_batch_servings}, "
            f"m = {draft.max_batch_servings}. La spec exige β ≥ 1 et m ≥ β."
        )

    known = set(
        session.scalars(select(CanonicalIngredient.id)).all()
    )
    lines: list[tuple[str, Decimal, Decimal]] = []
    seen: set[str] = set()
    demanded = Decimal("0")
    for row in draft.ingredients:
        ingredient_id = str(row.get("canonical_ingredient_id") or "").strip()
        if ingredient_id not in known:
            raise RecipeDraftInvalid(
                f"L'ingrédient {ingredient_id!r} n'est pas au catalogue "
                "canonique. Une recette ne peut pas citer une matière que le "
                "canon ne connaît pas : le solveur n'aurait rien à acheter."
            )
        if ingredient_id in seen:
            raise RecipeDraftInvalid(
                f"L'ingrédient {ingredient_id!r} figure deux fois. Une ligne "
                "par ingrédient : deux lignes finiraient par diverger."
            )
        seen.add(ingredient_id)
        fixed = _quantity(row.get("qty_fixed_per_batch_base_unit"), ingredient_id)
        marginal = _quantity(
            row.get("qty_marginal_per_serving_base_unit"), ingredient_id
        )
        demanded += fixed + marginal
        lines.append((ingredient_id, fixed, marginal))
    if demanded <= 0:
        raise RecipeDraftInvalid(
            "Toutes les quantités sont nulles : cette recette ne demande rien, "
            "et le solveur la servirait gratuitement (D25). Donner au moins une "
            "quantité par lot ou par portion."
        )

    recipe_id = _free_id(session, name)
    recipe = Recipe(
        id=recipe_id,
        name=name,
        dish_family_id=dish_family_id_of(recipe_id),
        original_servings=draft.original_servings,
        prep_time_fixed_h=_quantity(draft.prep_time_fixed_h, "prep_time_fixed_h"),
        prep_time_marginal_h=_quantity(
            draft.prep_time_marginal_h, "prep_time_marginal_h"
        ),
        min_batch_servings=draft.min_batch_servings,
        max_batch_servings=draft.max_batch_servings,
        # L'origine est inscrite dans la recette : une recette ajoutée depuis
        # l'application ne se confond pas avec une recette du seed, qui
        # reviendrait au prochain rechargement de celui-ci.
        tags={**(draft.tags or {}), "import_origin": "app"},
        required_equipment=list(draft.required_equipment or []),
        diet_flags=list(draft.diet_flags or []),
        allergen_flags=list(draft.allergen_flags or []),
    )
    for ingredient_id, fixed, marginal in lines:
        recipe.ingredients.append(
            RecipeIngredient(
                canonical_ingredient_id=ingredient_id,
                qty_fixed_per_batch_base_unit=fixed,
                qty_marginal_per_serving_base_unit=marginal,
            )
        )
    session.add(recipe)
    session.flush()
    return _summary(recipe)


def delete_recipe(
    session: Session, recipe_id: str, *, drop_plans: bool = False
) -> None:
    """Retire une recette, ses lignes, et — si on le demande — ses plans.

    Le refus par défaut n'est pas de la prudence décorative : `Plan.servings`
    cite les recettes par identifiant, sans clé étrangère, et l'écran de menu
    lit `recipes[rid]` sans garde. Retirer la recette sans le plan remplacerait
    un menu par une erreur 500.
    """
    recipe = session.get(Recipe, recipe_id)
    if recipe is None:
        raise RecipeNotFound(recipe_id)
    plans = [
        plan
        for plan in session.scalars(select(Plan)).all()
        if recipe_id in set(plan.servings or {}) | set(plan.cooked or {})
    ]
    if plans and not drop_plans:
        listing = ", ".join(f"#{plan.id} ({plan.status.value})" for plan in plans[:5])
        raise RecipeInUse(
            f"{len(plans)} plan(s) citent {recipe_id!r} : {listing}. Retirer la "
            "recette sans eux laisserait un menu illisible. Confirmer la "
            "suppression des plans pour continuer."
        )
    for plan in plans:
        session.delete(plan)
    session.delete(recipe)
    session.flush()


def _quantity(value: object, where: str) -> Decimal:
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise RecipeDraftInvalid(
            f"Quantité illisible pour {where} : {value!r}."
        ) from None
    if quantity < 0:
        raise RecipeDraftInvalid(
            f"Quantité négative pour {where} : {quantity}."
        )
    return quantity


def _free_id(session: Session, name: str) -> str:
    """Un identifiant stable, dérivé du nom, jamais déjà pris.

    Le suffixe numérique n'est pas décoratif : deux recettes du même nom
    existent (« Salade de pâtes » chez deux auteurs), et l'identifiant est la
    clé que les plans citent.
    """
    base = normalize_label(name).replace(" ", "_").replace("-", "_")
    base = "".join(c for c in base if c.isalnum() or c == "_").strip("_")[:56]
    base = base or "recette"
    taken = set(session.scalars(select(Recipe.id)).all())
    if base not in taken:
        return base
    for suffix in range(2, 100):
        candidate = f"{base}_{suffix}"
        if candidate not in taken:
            return candidate
    raise RecipeDraftInvalid(
        f"Cent recettes portent déjà le nom {name!r} : préciser le nom."
    )
