"""Calcul pur et explicable de la valeur nutritive d'une recette, par portion.

Module calqué sur ``recipe_costing`` : il ne connaît ni SQLAlchemy ni HTTP, et
reçoit des observations déjà normalisées. Il applique la même règle de fond que
l'ADR de sémantique des prix, transposée aux calories : **un total partiel n'est
jamais présenté comme un total**. Dès qu'une ligne ne se résout pas, les quatre
nombres par portion sortent à ``None`` et la recette nomme les ingrédients qui
l'en empêchent.

Trois façons pour une ligne de se résoudre :

- ``computed`` — l'ingrédient porte un aliment FCÉN retenu, et sa quantité se
  ramène en grammes de portion comestible (directement en masse, par densité
  curée en volume, par masse curée par unité en compte).
- ``negligible`` — aucun chiffre n'est disponible, mais le règlement déclare
  l'apport négligeable **pour cette quantité**, et la borne de l'erreur ainsi
  consentie remonte au total (``kcal_error_bound_per_serving``).
- ``gap`` — ni l'un ni l'autre. La raison est nommée, jamais silencieuse.

Le règlement est un **recours**, pas une surcharge : un ingrédient déclaré
négligeable qui porte tout de même un aliment FCÉN et une quantité convertible
est calculé pour de vrai. Sans ça, les 19 épices déjà appariées du corpus
auraient perdu leur chiffre au profit d'une borne, et le même fait aurait eu
deux lecteurs.

Hypothèse assumée : les quantités de recette sont des quantités d'achat
**crues**, donc l'appariement FCÉN vise la forme crue. La perte d'eau à la
cuisson ne change ni l'énergie ni les macros — mais le gras égoutté d'un bœuf
haché rissolé et l'huile absorbée en friture, oui. Limite réelle, nommée ici,
pas lissée.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Mapping, Sequence

from .confidence import (
    AUDITED_CONVERSION,
    ESTIMATED,
    EXACT,
    INCOMPLETE,
    worst_confidence,
)
from .nutrition_rules import (
    BASE_UNIT_MISMATCH,
    NEGLIGIBLE as _RULE_NEGLIGIBLE,
    NutritionRuleset,
    OVER_DECLARED_QUANTITY,
)
from .recipe_scaling import batch_requirements, field_of, servings_for
from .units import IncompatibleUnitsError, MissingDensityError, convert_qty

__all__ = [
    "CHOSEN_FOOD_ALREADY_ATTACHED",
    "AMBIGUOUS_CNF_FOOD",
    "CHOSEN_FOOD_NOT_ATTACHED",
    "COMPUTED",
    "GAP",
    "MISSING_DENSITY",
    "MISSING_GRAMS_PER_UNIT",
    "MISSING_NUTRIENT_VALUES",
    "NEGLIGIBLE",
    "NEGLIGIBLE_UNIT_MISMATCH",
    "NO_CNF_FOOD",
    "NO_QUANTITY_REQUIRED",
    "NutrientFacts",
    "NutritionIngredient",
    "NutritionLine",
    "OVER_NEGLIGIBLE_CEILING",
    "RecipeNutritionFacts",
    "RecipeNutritionModule",
    "retained_food_code",
    "UNKNOWN_INGREDIENT",
    "UNSUPPORTED_BASE_UNIT",
]

#: Comment une ligne s'est résolue.
COMPUTED = "computed"
NEGLIGIBLE = "negligible"
GAP = "gap"
NO_QUANTITY_REQUIRED = "no_quantity_required"

#: Pourquoi une ligne ne s'est pas résolue. Chaque valeur est une file de
#: travail différente : l'audit de couverture les compte séparément parce
#: qu'elles ne se corrigent pas de la même façon.
UNKNOWN_INGREDIENT = "unknown_ingredient"
NO_CNF_FOOD = "no_cnf_food"
AMBIGUOUS_CNF_FOOD = "ambiguous_cnf_food"
CHOSEN_FOOD_NOT_ATTACHED = "chosen_food_not_attached"
CHOSEN_FOOD_ALREADY_ATTACHED = "chosen_food_already_attached"

#: Raisons qui disent « le règlement est fautif », par opposition à
#: « la curation est incomplète ». Elles ne se laissent pas couvrir par le
#: recours d'apport négligeable : une règle cassée doit se voir.
_RULE_FAULTS = (CHOSEN_FOOD_NOT_ATTACHED, CHOSEN_FOOD_ALREADY_ATTACHED)
MISSING_NUTRIENT_VALUES = "missing_nutrient_values"
MISSING_DENSITY = "missing_density"
MISSING_GRAMS_PER_UNIT = "missing_grams_per_unit"
OVER_NEGLIGIBLE_CEILING = "over_negligible_ceiling"
NEGLIGIBLE_UNIT_MISMATCH = "negligible_unit_mismatch"
UNSUPPORTED_BASE_UNIT = "unsupported_base_unit"

#: Précision publiée : le dixième d'unité, comme le FCÉN publie ses teneurs
#: arrondies sur les étiquettes. Chaque ligne est arrondie puis sommée, pour
#: que les lignes affichées additionnent exactement le total affiché — la même
#: promesse que le devis de prix fait sur les cents.
_TENTH = Decimal("0.1")
_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class NutrientFacts:
    """Teneurs d'un aliment FCÉN, **par 100 g de portion comestible**."""

    food_code: str
    food_name: str
    kcal_per_100g: Decimal
    protein_g_per_100g: Decimal
    fat_g_per_100g: Decimal
    carbohydrate_g_per_100g: Decimal
    source_version: str


@dataclass(frozen=True)
class NutritionIngredient:
    """Ce que le canon sait d'un ingrédient, du point de vue nutritionnel.

    ``food_codes`` sont les aliments FCÉN **rattachés**, pas encore retenus :
    le pont a été curé pour l'identité commerciale et 26 ingrédients en portent
    plusieurs. Le choix se déclare dans le règlement, il ne se devine pas ici.
    """

    ingredient_id: str
    name: str
    family_id: str | None
    base_unit: str
    density_g_per_ml: Decimal | None
    grams_per_unit: Decimal | None
    food_codes: tuple[str, ...]


@dataclass(frozen=True)
class NutritionLine:
    ingredient_id: str
    qty_per_serving: Decimal
    base_unit: str
    grams_per_serving: Decimal | None
    resolution: str
    reason: str | None
    food_code: str | None
    kcal: Decimal | None
    protein_g: Decimal | None
    fat_g: Decimal | None
    carbohydrate_g: Decimal | None
    kcal_error_bound: Decimal
    protein_g_error_bound: Decimal
    fat_g_error_bound: Decimal
    carbohydrate_g_error_bound: Decimal
    confidence: str
    #: Provenance du chiffre quand la ligne est calculée ou déclarée
    #: négligeable ; raison détaillée du refus quand elle est bloquante. Une
    #: seule phrase à afficher, quel que soit le sort de la ligne.
    detail: str | None


@dataclass(frozen=True)
class RecipeNutritionFacts:
    recipe_id: str
    recipe_name: str
    servings: int
    status: str
    kcal_per_serving: Decimal | None
    protein_g_per_serving: Decimal | None
    fat_g_per_serving: Decimal | None
    carbohydrate_g_per_serving: Decimal | None
    #: Somme des bornes des lignes déclarées négligeables. Le total publié est
    #: donc « ce chiffre, à ± cette borne près » — et la borne s'affiche. Les
    #: quatre nombres portent la leur : ne borner que l'énergie laissait
    #: publier les macros comme exactes alors qu'une épice omise emporte
    #: jusqu'à un gramme de gras.
    kcal_error_bound_per_serving: Decimal | None
    protein_g_error_bound_per_serving: Decimal | None
    fat_g_error_bound_per_serving: Decimal | None
    carbohydrate_g_error_bound_per_serving: Decimal | None
    confidence: str
    rule_version: str
    lines: tuple[NutritionLine, ...]
    missing: tuple[tuple[str, str], ...]

    def as_dict(self) -> dict:
        return {
            **{
                key: value
                for key, value in asdict(self).items()
                if key not in ("lines", "missing")
            },
            "lines": [asdict(line) for line in self.lines],
            "missing": [
                {"canonical_ingredient_id": ingredient_id, "reason": reason}
                for ingredient_id, reason in self.missing
            ],
        }


class RecipeNutritionModule:
    @staticmethod
    def facts_all(
        recipes: Iterable[object],
        ingredients: Iterable[NutritionIngredient],
        foods: Iterable[NutrientFacts],
        rules: NutritionRuleset,
        servings: int | Mapping[str, int] | None = None,
    ) -> list[RecipeNutritionFacts]:
        catalogue = {row.ingredient_id: row for row in ingredients}
        table = {row.food_code: row for row in foods}
        return [
            _facts_for(
                recipe, catalogue, table, rules, servings_for(recipe, servings)
            )
            for recipe in recipes
        ]


def _facts_for(
    recipe: object,
    catalogue: Mapping[str, NutritionIngredient],
    foods: Mapping[str, NutrientFacts],
    rules: NutritionRuleset,
    servings: int,
) -> RecipeNutritionFacts:
    lines = [
        _line(ingredient_id, per_batch / servings, catalogue, foods, rules)
        for ingredient_id, per_batch in batch_requirements(recipe, servings)
    ]
    missing = tuple(
        (line.ingredient_id, line.reason or GAP)
        for line in lines
        if line.resolution == GAP
    )
    complete = not missing
    return RecipeNutritionFacts(
        recipe_id=str(field_of(recipe, "id")),
        recipe_name=str(field_of(recipe, "name")),
        servings=servings,
        status="complete" if complete else "incomplete",
        kcal_per_serving=_total(lines, "kcal") if complete else None,
        protein_g_per_serving=_total(lines, "protein_g") if complete else None,
        fat_g_per_serving=_total(lines, "fat_g") if complete else None,
        carbohydrate_g_per_serving=(
            _total(lines, "carbohydrate_g") if complete else None
        ),
        kcal_error_bound_per_serving=(
            _bound_total(lines, "kcal_error_bound") if complete else None
        ),
        protein_g_error_bound_per_serving=(
            _bound_total(lines, "protein_g_error_bound") if complete else None
        ),
        fat_g_error_bound_per_serving=(
            _bound_total(lines, "fat_g_error_bound") if complete else None
        ),
        carbohydrate_g_error_bound_per_serving=(
            _bound_total(lines, "carbohydrate_g_error_bound")
            if complete
            else None
        ),
        confidence=(
            INCOMPLETE
            if not complete
            else worst_confidence(*(line.confidence for line in lines))
        ),
        rule_version=rules.rule_version,
        lines=tuple(lines),
        missing=missing,
    )


def _line(
    ingredient_id: str,
    qty_per_serving: Decimal,
    catalogue: Mapping[str, NutritionIngredient],
    foods: Mapping[str, NutrientFacts],
    rules: NutritionRuleset,
) -> NutritionLine:
    ingredient = catalogue.get(ingredient_id)
    if ingredient is None:
        # Une recette peut citer un ingrédient que le canon ne connaît pas
        # (import de recettes en avance sur la curation). C'est un trou nommé,
        # pas une exception : les 160 autres recettes doivent rester lisibles.
        return _gap(
            ingredient_id,
            qty_per_serving,
            "?",
            UNKNOWN_INGREDIENT,
            f"L'ingrédient {ingredient_id!r} n'est pas au catalogue canonique.",
        )
    if qty_per_serving <= 0:
        return NutritionLine(
            ingredient_id=ingredient_id,
            qty_per_serving=qty_per_serving,
            base_unit=ingredient.base_unit,
            grams_per_serving=Decimal("0"),
            resolution=NO_QUANTITY_REQUIRED,
            reason=None,
            food_code=None,
            kcal=Decimal("0.0"),
            protein_g=Decimal("0.0"),
            fat_g=Decimal("0.0"),
            carbohydrate_g=Decimal("0.0"),
            kcal_error_bound=Decimal("0"),
            protein_g_error_bound=Decimal("0"),
            fat_g_error_bound=Decimal("0"),
            carbohydrate_g_error_bound=Decimal("0"),
            confidence=EXACT,
            detail=None,
        )

    # Une règle fautive passe AVANT le recours d'apport négligeable. Sinon le
    # recours répond d'abord et la faute disparaît : un « primary » qui désigne
    # un aliment non rattaché, sur un ingrédient par ailleurs déclaré
    # négligeable, sortait « complete » à 0 kcal sans que rien ne nomme la
    # règle cassée.
    _food, rule_fault, detail = _retained_food(ingredient, rules)
    if rule_fault in _RULE_FAULTS:
        return _gap(
            ingredient.ingredient_id,
            qty_per_serving,
            ingredient.base_unit,
            rule_fault,
            detail or "",
        )
    computed = _computed_line(ingredient, qty_per_serving, foods, rules)
    if computed is not None:
        return computed
    return _negligible_or_gap(ingredient, qty_per_serving, rules, foods)


def _computed_line(
    ingredient: NutritionIngredient,
    qty_per_serving: Decimal,
    foods: Mapping[str, NutrientFacts],
    rules: NutritionRuleset,
) -> NutritionLine | None:
    """Ligne calculée, ou ``None`` si un fait manque (le recours prend suite).

    Rend ``None`` — et non un trou — pour laisser le règlement d'apport
    négligeable répondre avant que l'échec soit constaté. La raison du premier
    échec est reconstruite par ``_negligible_or_gap`` si le recours n'existe pas.
    """
    food_code, _reason, _detail = _retained_food(ingredient, rules)
    if food_code is None:
        return None
    facts = foods.get(food_code)
    if facts is None:
        return None
    grams, confidence, _blocked = _grams_per_serving(ingredient, qty_per_serving)
    if grams is None:
        return None
    factor = grams / _HUNDRED
    choice = rules.food_choice(ingredient.ingredient_id)
    return NutritionLine(
        ingredient_id=ingredient.ingredient_id,
        qty_per_serving=qty_per_serving,
        base_unit=ingredient.base_unit,
        grams_per_serving=grams,
        resolution=COMPUTED,
        reason=None,
        food_code=food_code,
        kcal=_tenth(facts.kcal_per_100g * factor),
        protein_g=_tenth(facts.protein_g_per_100g * factor),
        fat_g=_tenth(facts.fat_g_per_100g * factor),
        carbohydrate_g=_tenth(facts.carbohydrate_g_per_100g * factor),
        kcal_error_bound=Decimal("0"),
        protein_g_error_bound=Decimal("0"),
        fat_g_error_bound=Decimal("0"),
        carbohydrate_g_error_bound=Decimal("0"),
        confidence=confidence,
        detail=(
            f"{facts.food_name} (FCÉN {facts.source_version}, aliment "
            f"{food_code})"
            + (f" — {choice.kind} : {choice.rationale}" if choice else "")
        ),
    )


def _negligible_or_gap(
    ingredient: NutritionIngredient,
    qty_per_serving: Decimal,
    rules: NutritionRuleset,
    foods: Mapping[str, NutrientFacts],
) -> NutritionLine:
    verdict = rules.negligible_verdict(
        ingredient_id=ingredient.ingredient_id,
        family_id=ingredient.family_id,
        base_unit=ingredient.base_unit,
        qty_per_serving=qty_per_serving,
    )
    if verdict.kind == _RULE_NEGLIGIBLE and verdict.claim is not None:
        claim = verdict.claim
        return NutritionLine(
            ingredient_id=ingredient.ingredient_id,
            qty_per_serving=qty_per_serving,
            base_unit=ingredient.base_unit,
            grams_per_serving=None,
            resolution=NEGLIGIBLE,
            reason=None,
            food_code=None,
            kcal=Decimal("0.0"),
            protein_g=Decimal("0.0"),
            fat_g=Decimal("0.0"),
            carbohydrate_g=Decimal("0.0"),
            kcal_error_bound=verdict.bounds.kcal,
            protein_g_error_bound=verdict.bounds.protein_g,
            fat_g_error_bound=verdict.bounds.fat_g,
            carbohydrate_g_error_bound=verdict.bounds.carbohydrate_g,
            confidence=ESTIMATED,
            detail=(
                f"Apport déclaré négligeable ({claim.scope} "
                f"{claim.scope_id}, règlement {rules.rule_version}) — borne "
                f"{verdict.kcal_bound} kcal. {claim.provenance}"
            ),
        )
    if verdict.kind == OVER_DECLARED_QUANTITY:
        return _gap(
            ingredient.ingredient_id,
            qty_per_serving,
            ingredient.base_unit,
            OVER_NEGLIGIBLE_CEILING,
            verdict.reason,
        )
    if verdict.kind == BASE_UNIT_MISMATCH:
        return _gap(
            ingredient.ingredient_id,
            qty_per_serving,
            ingredient.base_unit,
            NEGLIGIBLE_UNIT_MISMATCH,
            verdict.reason,
        )
    reason, detail = _blocking_reason(ingredient, rules, foods)
    return _gap(
        ingredient.ingredient_id,
        qty_per_serving,
        ingredient.base_unit,
        reason,
        detail,
    )


def _blocking_reason(
    ingredient: NutritionIngredient,
    rules: NutritionRuleset,
    foods: Mapping[str, NutrientFacts],
) -> tuple[str, str]:
    """Le premier fait qui manque, dans l'ordre où le calcul en a besoin.

    L'ordre est celui de ``_computed_line`` — aliment retenu, puis teneurs,
    puis conversion — et il est tenu par la même table de teneurs, pas par une
    reconstitution. Interrogé dans un autre ordre, le module bloquait une ligne
    pour une raison et en annonçait une autre : la file de revue de l'audit
    pointait alors un travail (« densité absente ») qui n'aurait rien débloqué.

    Les deux causes de conversion impossible sont demandées à
    ``_grams_per_serving`` plutôt que redérivées ici, pour la même raison.
    """
    food_code, reason, detail = _retained_food(ingredient, rules)
    if food_code is None:
        return reason or NO_CNF_FOOD, detail or ""
    if food_code not in foods:
        return (
            MISSING_NUTRIENT_VALUES,
            f"L'aliment FCÉN {food_code} retenu pour "
            f"{ingredient.ingredient_id!r} ne porte pas les quatre teneurs "
            "retenues (énergie, protéines, lipides, glucides).",
        )
    # La quantité sonde vaut 1 : ce qui manque à une conversion (densité,
    # masse par unité) ne dépend pas de la quantité à convertir.
    _grams, _confidence, conversion = _grams_per_serving(ingredient, Decimal("1"))
    if conversion is not None:
        return conversion
    # Inatteignable en principe : les trois faits ci-dessus sont les seuls que
    # `_computed_line` exige. Nommé quand même, plutôt qu'un `assert` muet.
    return (
        MISSING_NUTRIENT_VALUES,
        f"{ingredient.ingredient_id!r} n'a pas pu être calculé sans qu'un "
        "fait manquant soit identifiable.",
    )


def retained_food_code(
    ingredient: NutritionIngredient, rules: NutritionRuleset
) -> str | None:
    """Aliment FCÉN retenu pour cet ingrédient, ou ``None`` s'il n'y en a pas.

    Exposé parce que la dérivation des masses et des densités doit viser
    exactement l'aliment que le calcul utilisera. Le recalculer ailleurs, c'est
    accepter qu'une densité soit dérivée d'un aliment et appliquée à un autre.
    """
    food_code, _reason, _detail = _retained_food(ingredient, rules)
    return food_code


def _retained_food(
    ingredient: NutritionIngredient, rules: NutritionRuleset
) -> tuple[str | None, str | None, str | None]:
    """L'aliment FCÉN retenu pour cet ingrédient, ou pourquoi il n'y en a pas."""
    choice = rules.food_choice(ingredient.ingredient_id)
    if choice is not None:
        if choice.kind == "attachment" and ingredient.food_codes:
            return (
                None,
                CHOSEN_FOOD_ALREADY_ATTACHED,
                f"Le règlement retient l'aliment {choice.food_code} pour "
                f"{ingredient.ingredient_id!r} au titre de « attachment », "
                "qui déclare une curation d'identité restée vide. Or "
                f"l'ingrédient porte {_listed(ingredient.food_codes)}. Un "
                "aliment déjà rattaché se choisit par « primary », ou se "
                "récuse par « correction » — avec la justification qui dit "
                "pourquoi il ne convient pas.",
            )
        if choice.kind == "primary" and choice.food_code not in ingredient.food_codes:
            return (
                None,
                CHOSEN_FOOD_NOT_ATTACHED,
                f"Le règlement retient l'aliment {choice.food_code} pour "
                f"{ingredient.ingredient_id!r} au titre de « primary », mais "
                f"l'ingrédient porte {_listed(ingredient.food_codes)}. Un "
                "aliment non rattaché se déclare « correction » ou "
                "« substitution », avec la justification qui va avec.",
            )
        return choice.food_code, None, None
    if not ingredient.food_codes:
        return (
            None,
            NO_CNF_FOOD,
            f"Aucun aliment FCÉN n'est rattaché à "
            f"{ingredient.ingredient_id!r}.",
        )
    if len(ingredient.food_codes) > 1:
        return (
            None,
            AMBIGUOUS_CNF_FOOD,
            f"{ingredient.ingredient_id!r} porte plusieurs aliments FCÉN "
            f"({_listed(ingredient.food_codes)}) et le règlement n'en retient "
            "aucun. Choisir par tri serait arbitraire : les teneurs diffèrent.",
        )
    return ingredient.food_codes[0], None, None


def _grams_per_serving(
    ingredient: NutritionIngredient, qty_per_serving: Decimal
) -> tuple[Decimal | None, str, tuple[str, str] | None]:
    """Ramène la quantité en grammes de portion comestible, ou dit pourquoi non.

    Rend ``(grammes, confiance, None)`` en cas de succès et
    ``(None, incomplete, (raison, explication))`` sinon — la raison vient d'ici
    et de nulle part ailleurs.

    ``units.convert_qty`` reste la seule fonction de conversion du projet et
    continue de refuser compte↔masse. La masse curée par unité est résolue
    ici — c'est une donnée de curation, pas une conversion d'unités.
    """
    if ingredient.base_unit == "g":
        return qty_per_serving, EXACT, None
    if ingredient.base_unit == "unit":
        if not ingredient.grams_per_unit:
            return (
                None,
                INCOMPLETE,
                (
                    MISSING_GRAMS_PER_UNIT,
                    f"{ingredient.ingredient_id!r} se compte à l'unité et ne "
                    "porte pas de masse curée par unité (cnf_measure_weight "
                    "de type 6).",
                ),
            )
        return qty_per_serving * ingredient.grams_per_unit, AUDITED_CONVERSION, None
    try:
        return (
            convert_qty(
                qty_per_serving,
                ingredient.base_unit,
                "g",
                ingredient.density_g_per_ml,
            ),
            AUDITED_CONVERSION,
            None,
        )
    except MissingDensityError:
        return (
            None,
            INCOMPLETE,
            (
                MISSING_DENSITY,
                f"{ingredient.ingredient_id!r} se mesure en "
                f"{ingredient.base_unit} et ne porte pas de densité curée : la "
                "ramener en grammes de portion comestible exigerait un défaut "
                "à 1,0 g/ml, que le projet interdit.",
            ),
        )
    except IncompatibleUnitsError as error:
        # Une unité de base inconnue du convertisseur est une faute de canon,
        # pas un trou de curation : elle se dit, sans faire tomber les 160
        # autres recettes.
        return None, INCOMPLETE, (UNSUPPORTED_BASE_UNIT, str(error))


def _gap(
    ingredient_id: str,
    qty_per_serving: Decimal,
    base_unit: str,
    reason: str,
    detail: str | None,
) -> NutritionLine:
    return NutritionLine(
        ingredient_id=ingredient_id,
        qty_per_serving=qty_per_serving,
        base_unit=base_unit,
        grams_per_serving=None,
        resolution=GAP,
        reason=reason,
        food_code=None,
        kcal=None,
        protein_g=None,
        fat_g=None,
        carbohydrate_g=None,
        kcal_error_bound=Decimal("0"),
        protein_g_error_bound=Decimal("0"),
        fat_g_error_bound=Decimal("0"),
        carbohydrate_g_error_bound=Decimal("0"),
        confidence=INCOMPLETE,
        detail=detail or None,
    )


def _bound_total(lines: Sequence[NutritionLine], attribute: str) -> Decimal:
    return sum((getattr(line, attribute) for line in lines), Decimal("0"))


def _total(lines: Sequence[NutritionLine], attribute: str) -> Decimal:
    return sum(
        (getattr(line, attribute) or Decimal("0") for line in lines),
        Decimal("0"),
    )


def _tenth(value: Decimal) -> Decimal:
    return value.quantize(_TENTH, rounding=ROUND_HALF_UP)


def _listed(codes: Sequence[str]) -> str:
    return ", ".join(codes) if codes else "aucun"
