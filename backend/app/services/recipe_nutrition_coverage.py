"""Audit pur de la couverture nutritionnelle, et ordre de curation qui paie.

Le module ne lit ni fichiers ni base de données. Il **appelle le calcul
nutritionnel** et lit ses trous : c'est délibéré, et c'est la seule chose qui
empêche l'audit et le calcul de répondre autrement l'un que l'autre. Ce dépôt
s'est déjà fait prendre deux fois par deux lecteurs d'un même fait — l'audit de
couverture des prix annonçait une couverture que le calcul ne savait pas livrer,
et trois lecteurs du fichier de règles d'approvisionnement en tiraient trois
règles différentes.

**L'ordre de curation n'est pas celui qu'on croit.** Trier les ingrédients
bloquants par nombre de recettes touchées ne donne aucun palier : sur ce corpus,
la couverture progresse d'environ 0,8 recette par ingrédient curé, du premier au
deux-centième, parce que les recettes ont de longues listes et qu'il leur faut
presque tout. Trier par *recettes complétées* — une couverture d'ensemble, pas
une fréquence — change l'échelle : 33 ingrédients rendent calculables 50
recettes là où les 33 plus fréquents en rendent 40. La courbe de déblocage
publiée ici est celle-là, et les deux classements sont rendus côte à côte pour
que le choix reste vérifiable.

**Les rattachements existants sont des candidats, pas des preuves.** Le pont
canonique → FCÉN a été curé pour l'identité commerciale : ``mais`` a été créé
depuis « Pâtes, maïs, sèches » (357 kcal/100 g au lieu de 86). L'audit publie
donc la **carte des appariements retenus** — nom canonique, nom fédéral,
énergie — pour qu'un humain puisse relire les paires, et signale à part les
désaccords francs, ceux où aucun mot du nom canonique n'apparaît nulle part
dans le nom fédéral. Il ne tranche pas au-delà : distinguer « Épices, aneth,
frais » (une classe, appariement juste) de « Pâtes, maïs, sèches » (un produit
dérivé, appariement faux) demande les règles d'appariement, qui sont un
chantier à part.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from .nutrition_rules import NutritionRuleset
from .recipe_nutrition import (
    COMPUTED,
    GAP,
    NEGLIGIBLE,
    NutrientFacts,
    NutritionIngredient,
    RecipeNutritionFacts,
    RecipeNutritionModule,
)

__all__ = [
    "IngredientGap",
    "NutritionCoverageAudit",
    "RecipeCoverage",
    "RetainedFood",
    "SuspectFood",
    "UnlockStep",
    "audit_recipe_nutrition_coverage",
    "suspect_food_name",
]

#: Un mot plus court que ça ne discrimine rien (« de », « au », « en »).
_MIN_WORD = 4


@dataclass(frozen=True)
class IngredientGap:
    canonical_ingredient_id: str
    name: str
    reason: str
    base_unit: str
    recipe_occurrences: int
    blocked_recipes: int
    attached_food_codes: tuple[str, ...]
    detail: str | None


@dataclass(frozen=True)
class RecipeCoverage:
    recipe_id: str
    recipe_name: str
    ingredient_count: int
    complete: bool
    kcal_per_serving: Decimal | None
    kcal_error_bound_per_serving: Decimal | None
    missing: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class UnlockStep:
    """Une session de curation, et ce qu'elle rend calculable."""

    rank: int
    recipe_id: str
    added_ingredient_ids: tuple[str, ...]
    cumulative_ingredients: int
    recipes_computable: int


@dataclass(frozen=True)
class RetainedFood:
    """Appariement effectivement utilisé pour calculer, à relire tel quel."""

    canonical_ingredient_id: str
    ingredient_name: str
    food_code: str
    food_name: str
    kcal_per_100g: Decimal
    recipe_occurrences: int


@dataclass(frozen=True)
class SuspectFood:
    """Aliment retenu dont aucun mot ne recoupe le nom canonique."""

    canonical_ingredient_id: str
    ingredient_name: str
    food_code: str
    food_name: str


@dataclass(frozen=True)
class NutritionCoverageAudit:
    total_recipes: int
    complete_recipes: int
    incomplete_recipes: int
    total_recipe_ingredients: int
    blocking_ingredients: int
    gap_reason_counts: Mapping[str, int]
    negligible_lines: int
    computed_lines: int
    rule_version: str
    gaps: tuple[IngredientGap, ...]
    recipes: tuple[RecipeCoverage, ...]
    unlock_curve: tuple[UnlockStep, ...]
    retained_foods: tuple[RetainedFood, ...]
    suspect_foods: tuple[SuspectFood, ...]

    @property
    def ingredients_for_full_coverage(self) -> int:
        return self.unlock_curve[-1].cumulative_ingredients if self.unlock_curve else 0

    def as_dict(self) -> dict:
        return {
            "summary": {
                "total_recipes": self.total_recipes,
                "complete_recipes": self.complete_recipes,
                "incomplete_recipes": self.incomplete_recipes,
                "total_recipe_ingredients": self.total_recipe_ingredients,
                "blocking_ingredients": self.blocking_ingredients,
                "ingredients_for_full_coverage": self.ingredients_for_full_coverage,
                "gap_reason_counts": dict(self.gap_reason_counts),
                "computed_lines": self.computed_lines,
                "negligible_lines": self.negligible_lines,
                "rule_version": self.rule_version,
            },
            "gaps": [asdict(row) for row in self.gaps],
            "unlock_curve": [asdict(row) for row in self.unlock_curve],
            "retained_foods": [asdict(row) for row in self.retained_foods],
            "suspect_foods": [asdict(row) for row in self.suspect_foods],
            "recipes": [
                {
                    **asdict(row),
                    "missing": [
                        {"canonical_ingredient_id": ingredient_id, "reason": reason}
                        for ingredient_id, reason in row.missing
                    ],
                }
                for row in self.recipes
            ],
        }


def audit_recipe_nutrition_coverage(
    recipes: Sequence[object],
    ingredients: Iterable[NutritionIngredient],
    foods: Iterable[NutrientFacts],
    rules: NutritionRuleset,
) -> NutritionCoverageAudit:
    """Classe les trous par effet mesuré sur les recettes, et rien d'autre."""
    catalogue = {row.ingredient_id: row for row in ingredients}
    table = {row.food_code: row for row in foods}
    facts = RecipeNutritionModule.facts_all(
        recipes, catalogue.values(), table.values(), rules
    )

    occurrences: Counter[str] = Counter()
    blocked: Counter[str] = Counter()
    reasons: dict[str, str] = {}
    details: dict[str, str] = {}
    computed_lines = 0
    negligible_lines = 0
    for row in facts:
        for line in row.lines:
            occurrences[line.ingredient_id] += 1
            if line.resolution == COMPUTED:
                computed_lines += 1
            elif line.resolution == NEGLIGIBLE:
                negligible_lines += 1
            elif line.resolution == GAP:
                blocked[line.ingredient_id] += 1
                # Un même ingrédient bloque toujours pour la même raison, sauf
                # le plafond de quantité — qui dépend de la recette. La
                # première raison rencontrée est conservée, et l'ordre des
                # recettes est celui de l'appelant : reproductible.
                reasons.setdefault(line.ingredient_id, line.reason or GAP)
                if line.detail:
                    details.setdefault(line.ingredient_id, line.detail)

    gaps = tuple(
        IngredientGap(
            canonical_ingredient_id=ingredient_id,
            name=(
                catalogue[ingredient_id].name
                if ingredient_id in catalogue
                else ingredient_id
            ),
            reason=reasons[ingredient_id],
            base_unit=(
                catalogue[ingredient_id].base_unit
                if ingredient_id in catalogue
                else "?"
            ),
            recipe_occurrences=occurrences[ingredient_id],
            blocked_recipes=blocked[ingredient_id],
            attached_food_codes=(
                catalogue[ingredient_id].food_codes
                if ingredient_id in catalogue
                else ()
            ),
            detail=details.get(ingredient_id),
        )
        # Classement par effet, puis par identifiant : deux exécutions rendent
        # la même file de revue.
        for ingredient_id in sorted(
            blocked, key=lambda key: (-blocked[key], key)
        )
    )
    coverage = tuple(
        RecipeCoverage(
            recipe_id=row.recipe_id,
            recipe_name=row.recipe_name,
            ingredient_count=len(row.lines),
            complete=row.status == "complete",
            kcal_per_serving=row.kcal_per_serving,
            kcal_error_bound_per_serving=row.kcal_error_bound_per_serving,
            missing=row.missing,
        )
        for row in facts
    )
    return NutritionCoverageAudit(
        total_recipes=len(coverage),
        complete_recipes=sum(row.complete for row in coverage),
        incomplete_recipes=sum(not row.complete for row in coverage),
        total_recipe_ingredients=len(occurrences),
        blocking_ingredients=len(gaps),
        gap_reason_counts=dict(
            sorted(
                Counter(row.reason for row in gaps).items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        negligible_lines=negligible_lines,
        computed_lines=computed_lines,
        rule_version=rules.rule_version,
        gaps=gaps,
        recipes=coverage,
        unlock_curve=_unlock_curve(facts),
        retained_foods=_retained_foods(facts, catalogue, table),
        suspect_foods=_suspect_foods(facts, catalogue, table),
    )


def _unlock_curve(
    facts: Sequence[RecipeNutritionFacts],
) -> tuple[UnlockStep, ...]:
    """Ordre de curation par recettes complétées, et non par fréquence.

    Choix glouton : à chaque étape, la recette dont il reste le moins
    d'ingrédients bloquants. Une recette déjà couverte ne coûte rien et sort
    tout de suite; une recette et ses variantes de lot se complètent ensemble.
    """
    blocking = {row.recipe_id: {gap for gap, _reason in row.missing} for row in facts}
    curated: set[str] = set()
    steps: list[UnlockStep] = []
    remaining = set(blocking)
    while remaining:
        recipe_id = min(
            sorted(remaining), key=lambda key: len(blocking[key] - curated)
        )
        remaining.discard(recipe_id)
        added = tuple(sorted(blocking[recipe_id] - curated))
        curated.update(added)
        steps.append(
            UnlockStep(
                rank=len(steps) + 1,
                recipe_id=recipe_id,
                added_ingredient_ids=added,
                cumulative_ingredients=len(curated),
                recipes_computable=sum(
                    1 for gaps in blocking.values() if not gaps - curated
                ),
            )
        )
    return tuple(steps)


def _retained_foods(
    facts: Sequence[RecipeNutritionFacts],
    catalogue: Mapping[str, NutritionIngredient],
    foods: Mapping[str, NutrientFacts],
) -> tuple[RetainedFood, ...]:
    """Carte des appariements réellement utilisés, du plus cité au moins cité."""
    occurrences: Counter[str] = Counter()
    retained: dict[str, tuple[str, NutrientFacts]] = {}
    for row in facts:
        for line in row.lines:
            if line.resolution != COMPUTED or line.food_code is None:
                continue
            food = foods.get(line.food_code)
            ingredient = catalogue.get(line.ingredient_id)
            if food is None or ingredient is None:
                continue
            occurrences[line.ingredient_id] += 1
            retained[line.ingredient_id] = (ingredient.name, food)
    return tuple(
        RetainedFood(
            canonical_ingredient_id=ingredient_id,
            ingredient_name=name,
            food_code=food.food_code,
            food_name=food.food_name,
            kcal_per_100g=food.kcal_per_100g,
            recipe_occurrences=occurrences[ingredient_id],
        )
        for ingredient_id, (name, food) in sorted(
            retained.items(),
            key=lambda item: (-occurrences[item[0]], item[0]),
        )
    )


def _suspect_foods(
    facts: Sequence[RecipeNutritionFacts],
    catalogue: Mapping[str, NutritionIngredient],
    foods: Mapping[str, NutrientFacts],
) -> tuple[SuspectFood, ...]:
    return tuple(
        SuspectFood(
            canonical_ingredient_id=row.canonical_ingredient_id,
            ingredient_name=row.ingredient_name,
            food_code=row.food_code,
            food_name=row.food_name,
        )
        for row in _retained_foods(facts, catalogue, foods)
        if suspect_food_name(row.ingredient_name, row.food_name)
    )


def suspect_food_name(ingredient_name: str, food_name: str) -> bool:
    """Aucun mot significatif du nom canonique n'apparaît dans le nom fédéral.

    Désaccord franc, donc peu bavard : « Épices, aneth, frais » pour « Aneth
    frais » passe (le mot est là), et c'est voulu — le premier segment fédéral
    est souvent une classe, pas un démenti. Ce qui ne passe pas, c'est un nom
    qui ne partage rien, comme le ferait une correspondance faite sur un code
    plutôt que sur un aliment.

    La normalisation est locale et minimale : les pluriels sont ramenés par
    troncature (« Asperges » contre « Asperge, crue »). ``normalize_label``
    existe dans ``ingestion``, mais l'importer d'ici tirerait la couche base de
    données dans un module que le garde-fou de pureté exige importable sans elle.
    """
    canonical_words = _words(ingredient_name)
    food_words = _words(food_name)
    if not canonical_words or not food_words:
        return False
    return not any(
        _same_word(canonical, published)
        for canonical in canonical_words
        for published in food_words
    )


def _same_word(left: str, right: str) -> bool:
    """Égalité tolérante au pluriel et aux formes suffixées."""
    short, long = sorted((left, right), key=len)
    return long.startswith(short)


def _words(text: str) -> tuple[str, ...]:
    folded = "".join(
        character
        for character in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(character) != "Mn"
    )
    return tuple(
        word
        for word in "".join(
            character if character.isalnum() else " " for character in folded
        ).split()
        if len(word) >= _MIN_WORD
    )
