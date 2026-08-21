"""Façade SQL du module pur de calcul nutritionnel.

Elle assemble quatre faits qui vivent chacun à un endroit différent, et n'en
invente aucun :

1. les recettes et leurs quantités (``catalog.recipe``) ;
2. ce que le canon sait de chaque ingrédient — unité de base, densité curée,
   famille (``catalog.canonical_ingredient``) ;
3. les aliments FCÉN rattachés (``catalog.canonical_ingredient_external_ref``)
   et leurs teneurs publiées (``staging.cnf_nutrient_amount``) ;
4. le règlement versionné (``config/nutrition-rules.json``) : apports déclarés
   négligeables, et aliment retenu quand le rattachement est ambigu ou fautif.

**Lecture de ``staging``, jamais d'écriture.** La règle du projet interdit aux
services de *court-circuiter* la normalisation, pas de lire une table
d'atterrissage : ``offer_resolution`` lit déjà ``staging.raw_offer`` pour
alimenter sa file de revue, sous le même invariant. La copie FCÉN n'est pas
non plus une file transitoire : elle est versionnée par ``source_version`` et
scellée par ``archive_sha256``, donc rejouable à l'identique.

**La masse d'un ingrédient compté** est lue là où la convention existe déjà —
``verified_grams_per_unit`` dans ``config/cook_recipe_curation.json``, avec sa
provenance dans ``grams_per_unit_provenance``. Aucun des ingrédients comptés du
corpus n'y figure aujourd'hui : ils ressortent donc bloquants, et le remplir
est un chantier à part entière (une masse par unité dérivée du FCÉN). Les
masses seulement *estimées* ne sont pas lues : une estimation suffit à
convertir une quantité d'achat, pas à publier une valeur nutritive.
"""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..ingestion.cnf import RETAINED_NUTRIENT_CODES
from ..models import (
    CanonicalIngredient,
    CanonicalIngredientExternalRef,
    CnfFoodCandidate,
    CnfNutrientAmount,
    CnfNutrientName,
    Recipe,
)
from .nutrition_rules import (
    NutritionRuleset,
    NutritionRulesInvalid,
    parse_nutrition_rules,
    parse_verified_unit_masses,
)
from .recipe_nutrition import (
    NutrientFacts,
    NutritionIngredient,
    RecipeNutritionFacts,
    RecipeNutritionModule,
)
from .recipe_scaling import RecipeNotScalableError, servings_for

__all__ = [
    "NutritionDataUnavailable",
    "NutritionRulesUnavailable",
    "RecipeNotScalableError",
    "nutrition_facts",
    "rules_path",
]

_RULES_FILENAME = "nutrition-rules.json"
_UNIT_CURATION_FILENAME = "cook_recipe_curation.json"

#: Source du pont canonique → FCÉN, telle que la curation l'écrit.
_SOURCE = "cnf"

#: Codes FCÉN des quatre teneurs retenues, et le champ qu'elles renseignent.
#: Les codes eux-mêmes viennent de l'import : un deuxième tuple ici finirait
#: par désigner un autre périmètre que celui réellement chargé.
_ENERGY, _PROTEIN, _FAT, _CARBOHYDRATE = "208", "203", "204", "205"

#: Unité publiée attendue pour chacune. Le FCÉN ne convertit rien à l'import
#: (« la conversion est une décision du consommateur ») : si une édition future
#: publiait l'énergie en kilojoules, le calcul serait faux d'un facteur 4,184
#: sans rien changer d'autre. La façade refuse plutôt que de le supposer.
_EXPECTED_UNITS = {
    _ENERGY: "kilocalorie",
    _PROTEIN: "gram",
    _FAT: "gram",
    _CARBOHYDRATE: "gram",
}


class NutritionRulesUnavailable(RuntimeError):
    """Le règlement nutritionnel est introuvable ou illisible.

    Nommée pour la même raison que ``ProcurementRulesUnavailable`` : sans elle,
    un fichier de règles absent du conteneur livré remontait en
    ``FileNotFoundError`` brut depuis le fond de la couche services, et la
    route entière répondait 500 au premier appel — dans la pile livrée
    seulement. Vérifier ``MENU_CONFIG_DIR`` et le montage de ``config/``.
    """


class NutritionDataUnavailable(RuntimeError):
    """Les teneurs FCÉN ne sont pas chargées dans cette base.

    Distincte d'un trou de curation : ce n'est pas l'ingrédient qui manque, c'est
    l'archive fédérale qui n'a pas été importée. Sans cette distinction, une
    base neuve annonçait 309 ingrédients « sans teneur » et laissait croire à un
    chantier de curation là où il suffisait de rejouer un import.
    """


def rules_path() -> Path:
    return Path(settings.config_dir) / _RULES_FILENAME


def nutrition_facts(
    session: Session,
    *,
    recipe_id: str | None = None,
    servings: int | None = None,
) -> tuple[RecipeNutritionFacts, ...]:
    """Valeur nutritive par portion, avec preuve et niveau de confiance."""
    recipe_stmt = select(Recipe).options(selectinload(Recipe.ingredients))
    if recipe_id is not None:
        recipe_stmt = recipe_stmt.where(Recipe.id == recipe_id)
    recipes = tuple(session.scalars(recipe_stmt.order_by(Recipe.id)))
    if recipe_id is not None and not recipes:
        raise LookupError(f"Recette '{recipe_id}' introuvable.")

    # Le rendement demandé est arbitré avant tout chargement : une recette qui
    # ne sait pas se rendre en 3 portions le dit même quand l'archive fédérale
    # n'est pas là. Sinon la panne de déploiement (503) masquait l'erreur
    # d'appel (422), et l'appelant corrigeait la mauvaise chose.
    resolved = {
        recipe.id: servings_for(recipe, servings) for recipe in recipes
    }
    rules = _load_rules()
    ingredients = _ingredients(session, rules)
    foods = _foods(session, ingredients, rules)
    return tuple(
        RecipeNutritionModule.facts_all(
            recipes, ingredients, foods, rules, servings=resolved
        )
    )


def _ingredients(
    session: Session, rules: NutritionRuleset
) -> tuple[NutritionIngredient, ...]:
    attached: dict[str, list[str]] = {}
    for ingredient_id, food_code in session.execute(
        select(
            CanonicalIngredientExternalRef.canonical_ingredient_id,
            CanonicalIngredientExternalRef.external_id,
        )
        .where(
            CanonicalIngredientExternalRef.source == _SOURCE,
            # L'édition est dans la clé unique de la table : le même code
            # d'aliment y vit une fois par archive importée. Sans ce filtre,
            # une deuxième édition faisait porter `("2401", "2401")` à
            # `oignon_jaune`, que le module lisait comme une ambiguïté et qui
            # bloquait 35 recettes en citant deux fois le même aliment.
            CanonicalIngredientExternalRef.source_version
            == rules.source_version,
        )
        # Sans ordre explicite, deux appels pouvaient citer les aliments
        # rattachés dans deux ordres différents, et le message d'ambiguïté
        # changer d'un appel à l'autre. Une preuve qui bouge n'est pas une
        # preuve — même arbitrage que le devis de prix.
        .order_by(
            CanonicalIngredientExternalRef.canonical_ingredient_id,
            CanonicalIngredientExternalRef.external_id,
        )
    ):
        attached.setdefault(ingredient_id, []).append(food_code)

    masses = _verified_unit_masses()
    return tuple(
        NutritionIngredient(
            ingredient_id=row.id,
            name=row.name,
            family_id=row.family_id,
            base_unit=row.base_unit,
            density_g_per_ml=row.density_g_per_ml,
            grams_per_unit=masses.get(row.id),
            food_codes=tuple(attached.get(row.id, ())),
        )
        for row in session.scalars(
            select(CanonicalIngredient).order_by(CanonicalIngredient.id)
        )
    )


def _foods(
    session: Session,
    ingredients: tuple[NutritionIngredient, ...],
    rules: NutritionRuleset,
) -> tuple[NutrientFacts, ...]:
    needed = {code for row in ingredients for code in row.food_codes}
    needed.update(choice.food_code for choice in rules.food_choices)
    if not needed:
        return ()

    _refuse_unexpected_units(session, rules.source_version)
    amounts: dict[str, dict[str, Decimal]] = {}
    versions: dict[str, str] = {}
    for row in session.execute(
        select(
            CnfNutrientAmount.food_code,
            CnfNutrientAmount.nutrient_code,
            CnfNutrientAmount.amount_per_100g,
            CnfNutrientAmount.source_version,
        ).where(
            CnfNutrientAmount.food_code.in_(needed),
            CnfNutrientAmount.nutrient_code.in_(RETAINED_NUTRIENT_CODES),
            # Une teneur par édition, et l'import ne supprime pas les
            # précédentes. Sans ce filtre, deux éditions chargées donnaient
            # l'énergie d'une et les lipides de l'autre — selon l'ordre
            # d'arrivée des lignes, donc d'une requête à l'autre — et la
            # provenance publiée nommait l'édition de la dernière ligne lue.
            CnfNutrientAmount.source_version == rules.source_version,
        )
    ):
        amounts.setdefault(row.food_code, {})[row.nutrient_code] = (
            row.amount_per_100g
        )
        versions[row.food_code] = row.source_version
    if not amounts:
        raise NutritionDataUnavailable(
            f"Aucune teneur FCÉN de l'édition {rules.source_version} chargée "
            f"dans cette base pour les {len(needed)} aliments rattachés au "
            "canon. Rejouer l'import : "
            "python -m app.ingestion.cnf --archive "
            "../data/cnf_fcen_all-files-data_2026.zip --tables nutrients"
        )

    names = dict(
        session.execute(
            select(
                CnfFoodCandidate.food_code,
                CnfFoodCandidate.food_description_fr,
            ).where(CnfFoodCandidate.food_code.in_(amounts))
        ).all()
    )
    return tuple(
        NutrientFacts(
            food_code=food_code,
            food_name=names.get(food_code, f"aliment {food_code}"),
            kcal_per_100g=values[_ENERGY],
            protein_g_per_100g=values[_PROTEIN],
            fat_g_per_100g=values[_FAT],
            carbohydrate_g_per_100g=values[_CARBOHYDRATE],
            source_version=versions[food_code],
        )
        for food_code, values in sorted(amounts.items())
        # Un aliment qui ne porte pas les quatre teneurs ne rend pas un profil
        # partiel : le module le déclare bloquant, faute de le trouver ici.
        if all(code in values for code in (_ENERGY, _PROTEIN, _FAT, _CARBOHYDRATE))
    )


def _refuse_unexpected_units(session: Session, source_version: str) -> None:
    published = dict(
        session.execute(
            select(CnfNutrientName.nutrient_code, CnfNutrientName.nutrient_unit)
            .where(
                CnfNutrientName.nutrient_code.in_(_EXPECTED_UNITS),
                CnfNutrientName.source_version == source_version,
            )
        ).all()
    )
    wrong = {
        code: unit
        for code, unit in published.items()
        if unit.strip().lower() != _EXPECTED_UNITS[code]
    }
    if wrong:
        raise NutritionDataUnavailable(
            "Le FCÉN chargé publie des unités inattendues pour les teneurs "
            f"retenues ({wrong}). Les convertir sans le dire produirait des "
            "valeurs plausibles et fausses; le calcul s'arrête."
        )


@lru_cache(maxsize=None)
def _load_rules_cached(path: str) -> NutritionRuleset:
    """Le règlement est relu une fois, pas à chaque requête HTTP."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise NutritionRulesUnavailable(
            f"Règlement nutritionnel introuvable: {path}. "
            "Vérifier MENU_CONFIG_DIR et la présence du dossier de configuration."
        ) from error
    except json.JSONDecodeError as error:
        raise NutritionRulesUnavailable(
            f"Règlement nutritionnel illisible: {path} ({error})."
        ) from error
    try:
        return parse_nutrition_rules(payload)
    except NutritionRulesInvalid as error:
        # Un règlement à moitié écrit est plus dangereux qu'un règlement
        # absent : il produirait des totaux plausibles. Il devient une panne de
        # déploiement, comme son absence.
        raise NutritionRulesUnavailable(
            f"Règlement nutritionnel invalide: {path} — {error}"
        ) from error


def _load_rules() -> NutritionRuleset:
    return _load_rules_cached(str(rules_path()))


@lru_cache(maxsize=None)
def _verified_unit_masses_cached(path: str) -> dict[str, Decimal]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        # Ce fichier sert d'abord à l'import des recettes; son absence n'est
        # pas une panne du calcul nutritionnel. Les ingrédients comptés
        # ressortent simplement bloquants, en le disant.
        return {}
    return parse_verified_unit_masses(payload)


def _verified_unit_masses() -> dict[str, Decimal]:
    return _verified_unit_masses_cached(
        str(Path(settings.config_dir) / _UNIT_CURATION_FILENAME)
    )
