"""Écrire un choix d'aliment FCÉN retenu, avec sa provenance rendue.

Le règlement nutritionnel (``config/nutrition-rules.json``) porte les aliments
retenus pour la nutrition — un par ingrédient, daté, motivé (D30). Ce module
est ce qui les écrit. Il existe pour deux raisons que la relecture ne couvre
pas :

1. **La provenance n'est pas saisie.** Elle est rendue depuis les quatre
   teneurs publiées par l'archive fédérale. Une provenance rétro-calculée
   depuis la valeur retenue se lit comme vérifiable sans l'être; c'est arrivé
   ici, sur les densités, et c'est le genre de faute qu'aucune relecture
   n'attrape parce que le texte est plausible.
2. **Le contrôle que le parseur ne peut pas faire.** ``parse_nutrition_rules``
   ne voit pas le pont canonique → FCÉN, donc il ne peut pas juger qu'un
   « attachment » déclare une curation d'identité vide alors qu'elle ne l'est
   pas, ni qu'un « primary » désigne un aliment non rattaché. Le calcul, lui,
   le refuse à l'exécution — trop tard pour la personne qui écrit l'entrée.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from app.services.nutrition_rules import CHOICE_KINDS
from app.services.recipe_nutrition import NutrientFacts

__all__ = [
    "FoodChoiceDecision",
    "FoodChoiceRefused",
    "merge_food_choices",
    "render_food_choices",
]


class FoodChoiceRefused(ValueError):
    """L'entrée n'est pas écrite, et le refus dit ce qui manque.

    Nommée, parce qu'une entrée à moitié justifiée est pire qu'une entrée
    absente : l'ingrédient cesse de bloquer et le chiffre sort quand même.
    """


@dataclass(frozen=True)
class FoodChoiceDecision:
    """Une décision humaine : cet ingrédient, cet aliment, à ce titre, parce que.

    La provenance ne figure pas ici — c'est tout l'objet du module.
    """

    ingredient_id: str
    food_code: str
    kind: str
    rationale: str


def render_food_choices(
    decisions: Iterable[FoodChoiceDecision],
    foods: Mapping[str, NutrientFacts],
    attached: Mapping[str, Sequence[str]],
) -> tuple[dict, ...]:
    """Rend les entrées du règlement, ou refuse en nommant le défaut.

    ``attached`` porte **tous** les ingrédients du canon — la séquence est vide
    quand rien n'est rattaché. C'est ce qui permet de distinguer « ne porte
    aucun aliment » de « n'existe pas », deux cas qu'un ``get`` par défaut
    confondait : une faute de frappe rendait alors une entrée d'apparence
    versionnée qui ne désignait rien, et la couverture ne bougeait pas.
    """
    rendered: list[dict] = []
    seen: set[str] = set()
    for decision in decisions:
        if decision.ingredient_id in seen:
            raise FoodChoiceRefused(
                f"{decision.ingredient_id!r} est décidé deux fois dans le même "
                "lot : le choix ne serait pas un choix."
            )
        seen.add(decision.ingredient_id)
        if decision.kind not in CHOICE_KINDS:
            raise FoodChoiceRefused(
                f"{decision.ingredient_id!r} : titre {decision.kind!r} inconnu "
                f"(attendu : {', '.join(CHOICE_KINDS)}). Écrit tel quel, il "
                "rendrait le règlement illisible pour son propre parseur — donc "
                "l'API en 503 sur toutes les recettes."
            )
        if decision.ingredient_id not in attached:
            raise FoodChoiceRefused(
                f"{decision.ingredient_id!r} n'est pas au catalogue canonique. "
                "Une entrée qui ne désigne aucun ingrédient se lit comme une "
                "décision prise, et ne débloque rien."
            )
        rationale = decision.rationale.strip()
        if not rationale:
            raise FoodChoiceRefused(
                f"{decision.ingredient_id!r} : aucune justification écrite. "
                "Un aliment retenu sans motif n'est pas une décision, c'est un "
                "tri."
            )
        facts = foods.get(decision.food_code)
        if facts is None:
            raise FoodChoiceRefused(
                f"{decision.ingredient_id!r} : l'archive ne publie pas "
                f"l'aliment {decision.food_code!r}. Une provenance ne se "
                "rédige pas pour un aliment introuvable."
            )
        carried = tuple(attached[decision.ingredient_id])
        _refuse_kind_against_bridge(decision, carried)
        rendered.append(
            {
                "ingredient_id": decision.ingredient_id,
                "food_code": decision.food_code,
                "kind": decision.kind,
                "rationale": rationale,
                "provenance": _provenance(facts),
            }
        )
    return tuple(rendered)


def merge_food_choices(
    existing: Iterable[Mapping], additions: Iterable[Mapping]
) -> list[dict]:
    """Ajoute les entrées au règlement, sans jamais en redécider une.

    Une entrée déjà écrite est une décision datée : la remplacer en silence
    ferait de deux décisions une seule, sans dire laquelle a survécu.
    """
    merged = {str(row["ingredient_id"]): dict(row) for row in existing}
    for row in additions:
        ingredient_id = str(row["ingredient_id"])
        if ingredient_id in merged:
            raise FoodChoiceRefused(
                f"{ingredient_id!r} porte déjà un choix d'aliment "
                f"({merged[ingredient_id]['food_code']}). Le changer se fait "
                "en relisant l'entrée existante, pas en la recouvrant."
            )
        merged[ingredient_id] = dict(row)
    return [merged[key] for key in sorted(merged)]


def _refuse_kind_against_bridge(
    decision: FoodChoiceDecision, carried: Sequence[str]
) -> None:
    if decision.kind == "attachment" and carried:
        raise FoodChoiceRefused(
            f"{decision.ingredient_id!r} : « attachment » déclare une curation "
            f"d'identité restée vide, or l'ingrédient porte {', '.join(carried)}. "
            "Un aliment déjà rattaché se choisit par « primary », ou se récuse "
            "par « correction »."
        )
    if decision.kind == "primary" and decision.food_code not in carried:
        raise FoodChoiceRefused(
            f"{decision.ingredient_id!r} : « primary » choisit parmi les "
            f"aliments rattachés, et l'ingrédient porte "
            f"{', '.join(carried) or 'aucun aliment'}. Un aliment non rattaché "
            "se déclare « attachment », « correction » ou « substitution »."
        )


def _provenance(facts: NutrientFacts) -> str:
    return (
        f"FCÉN {facts.source_version}, aliment {facts.food_code} "
        f"« {facts.food_name} » : {_number(facts.kcal_per_100g)} kcal, "
        f"{_number(facts.protein_g_per_100g)} g de protéines, "
        f"{_number(facts.fat_g_per_100g)} g de lipides, "
        f"{_number(facts.carbohydrate_g_per_100g)} g de glucides par 100 g."
    )


def _number(value: Decimal) -> str:
    """Le nombre publié, sans zéros décoratifs, à la virgule française."""
    trimmed = value.normalize()
    if trimmed == trimmed.to_integral_value():
        trimmed = trimmed.quantize(Decimal("1"))
    return f"{trimmed:f}".replace(".", ",")
