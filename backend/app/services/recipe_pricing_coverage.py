"""Audit pur de la couverture de prix des recettes.

Le module ne lit ni fichiers ni base de données. Il classe chaque ingrédient
utilisé selon l'étape la plus avancée atteinte par au moins un produit
commercial, puis propage les blocages aux recettes.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Iterable, Mapping, Sequence

from .supply_rules import SupplyRule, resolve_supply

#: L'audit n'a besoin que de l'identifiant, du type et de la source, mais lit le
#: même fichier que le calcul de prix : c'est le même objet, sous l'ancien nom.
CoverageSupplyRule = SupplyRule

PRICED = "priced"
MISSING_PRICE = "missing_price"
INCOMPATIBLE_PACKAGE_DIMENSION = "incompatible_package_dimension"
UNPARSED_OR_VARIABLE_PACKAGE = "unparsed_or_variable_package"
NO_APPROVED_PRODUCT = "no_approved_product"

_REASON_STATUS = {
    "missing_or_invalid_price": MISSING_PRICE,
    "package_dimension_incompatible": INCOMPATIBLE_PACKAGE_DIMENSION,
    "package_not_fixed_or_unparsed": UNPARSED_OR_VARIABLE_PACKAGE,
}
_STATUS_PRIORITY = {
    NO_APPROVED_PRODUCT: 0,
    UNPARSED_OR_VARIABLE_PACKAGE: 1,
    INCOMPATIBLE_PACKAGE_DIMENSION: 2,
    MISSING_PRICE: 3,
    PRICED: 4,
}


@dataclass(frozen=True)
class ProductDecisionEvidence:
    source: str
    status: str
    canonical_ingredient_id: str | None
    reason: str


@dataclass(frozen=True)
class IngredientCoverage:
    canonical_ingredient_id: str
    status: str
    recipe_occurrences: int
    sources: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RecipeCoverage:
    recipe_id: str
    recipe_name: str
    ingredient_count: int
    complete: bool
    missing: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class CoverageAudit:
    ingredient_status_counts: Mapping[str, int]
    total_recipe_ingredients: int
    total_recipes: int
    complete_recipes: int
    incomplete_recipes: int
    ingredients: tuple[IngredientCoverage, ...]
    recipes: tuple[RecipeCoverage, ...]

    def as_dict(self) -> dict:
        return {
            "summary": {
                "total_recipes": self.total_recipes,
                "complete_recipes": self.complete_recipes,
                "incomplete_recipes": self.incomplete_recipes,
                "total_recipe_ingredients": self.total_recipe_ingredients,
                "ingredient_status_counts": dict(self.ingredient_status_counts),
            },
            "ingredients": [asdict(row) for row in self.ingredients],
            "recipes": [
                {
                    **asdict(row),
                    "missing": [
                        {"canonical_ingredient_id": ingredient_id, "status": status}
                        for ingredient_id, status in row.missing
                    ],
                }
                for row in self.recipes
            ],
        }


def audit_recipe_pricing_coverage(
    recipes: Sequence[dict],
    decisions: Iterable[ProductDecisionEvidence],
    supply_rules: Iterable[CoverageSupplyRule] = (),
) -> CoverageAudit:
    """Retourne une classification exclusive et reproductible de la couverture."""
    recipe_occurrences = Counter(
        ingredient["canonical_ingredient_id"]
        for recipe in recipes
        for ingredient in recipe["ingredients"]
    )
    # Les preuves de TOUS les ingrédients sont indexées, pas seulement celles
    # des ingrédients cités par une recette : la source d'une règle dérivée
    # (le citron pour le jus de citron) n'apparaît souvent dans aucune recette,
    # et le filtrage la rendait invisible — la chaîne ne pouvait alors jamais se
    # résoudre, quelle que soit la boucle qui la parcourait.
    evidence_by_ingredient: dict[str, list[ProductDecisionEvidence]] = defaultdict(list)
    for decision in decisions:
        if decision.canonical_ingredient_id is not None:
            evidence_by_ingredient[decision.canonical_ingredient_id].append(decision)

    rules_by_ingredient = {rule.ingredient_id: rule for rule in supply_rules}
    status_by_ingredient = {
        ingredient_id: _status_of(ingredient_id, evidence_by_ingredient)
        for ingredient_id in sorted(recipe_occurrences)
    }

    # Une règle d'approvisionnement décide du statut à la place des produits :
    # un essentiel est couvert sans achat, un dérivé l'est si la fin de sa
    # chaîne l'est. La résolution est celle du calcul de prix — un point fixe
    # propre à l'audit avait fini par répondre autrement que lui.
    for ingredient_id in list(status_by_ingredient):
        if ingredient_id not in rules_by_ingredient:
            continue
        supply = resolve_supply(ingredient_id, rules_by_ingredient)
        if supply.kind == "essential":
            status_by_ingredient[ingredient_id] = PRICED
        elif supply.kind == "derived":
            source = supply.procurement_ingredient_id
            source_status = _status_of(source, evidence_by_ingredient)
            if source_status == PRICED:
                status_by_ingredient[ingredient_id] = PRICED

    ingredient_rows = []
    for ingredient_id in sorted(recipe_occurrences):
        evidence = evidence_by_ingredient[ingredient_id]
        rule = rules_by_ingredient.get(ingredient_id)
        rule_resolved = (
            status_by_ingredient[ingredient_id] == PRICED and rule is not None
        )
        rule_source = f"supply_rule:{rule.kind}" if rule_resolved else None
        rule_reason = (
            f"resolved_by_{rule.kind}_supply_rule" if rule_resolved else None
        )
        ingredient_rows.append(
            IngredientCoverage(
                canonical_ingredient_id=ingredient_id,
                status=status_by_ingredient[ingredient_id],
                recipe_occurrences=recipe_occurrences[ingredient_id],
                sources=tuple(
                    sorted(
                        {row.source for row in evidence}
                        | ({rule_source} if rule_source else set())
                    )
                ),
                reasons=tuple(
                    sorted(
                        {row.reason for row in evidence}
                        | ({rule_reason} if rule_reason else set())
                    )
                ),
            )
        )

    recipe_rows = []
    for recipe in recipes:
        ingredient_ids = sorted(
            {row["canonical_ingredient_id"] for row in recipe["ingredients"]}
        )
        missing = tuple(
            (ingredient_id, status_by_ingredient[ingredient_id])
            for ingredient_id in ingredient_ids
            if status_by_ingredient[ingredient_id] != PRICED
        )
        recipe_rows.append(
            RecipeCoverage(
                recipe_id=str(recipe["id"]),
                recipe_name=str(recipe["name"]),
                ingredient_count=len(ingredient_ids),
                complete=not missing,
                missing=missing,
            )
        )

    status_counts = Counter(row.status for row in ingredient_rows)
    ordered_counts = {
        status: status_counts.get(status, 0)
        for status in sorted(_STATUS_PRIORITY, key=_STATUS_PRIORITY.get, reverse=True)
    }
    complete = sum(row.complete for row in recipe_rows)
    return CoverageAudit(
        ingredient_status_counts=ordered_counts,
        total_recipe_ingredients=len(ingredient_rows),
        total_recipes=len(recipe_rows),
        complete_recipes=complete,
        incomplete_recipes=len(recipe_rows) - complete,
        ingredients=tuple(ingredient_rows),
        recipes=tuple(recipe_rows),
    )


def _status_of(
    ingredient_id: str | None,
    evidence_by_ingredient: Mapping[str, Sequence[ProductDecisionEvidence]],
) -> str:
    """Étape la plus avancée atteinte par au moins un produit de cet ingrédient."""
    statuses = [
        _coverage_status(row) for row in evidence_by_ingredient.get(ingredient_id or "", ())
    ]
    return max(statuses or [NO_APPROVED_PRODUCT], key=_STATUS_PRIORITY.__getitem__)


def _coverage_status(decision: ProductDecisionEvidence) -> str:
    if decision.status == "matched":
        return PRICED
    return _REASON_STATUS.get(decision.reason, NO_APPROVED_PRODUCT)
