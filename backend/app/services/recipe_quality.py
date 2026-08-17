"""Contrôle de vraisemblance des recettes, avant tout calcul de prix.

Un devis peut être arithmétiquement juste et rester faux : si la recette
importée demande « 1 g d'aubergine » là où elle voulait dire une aubergine
entière, le coût calculé est 0,00 $ et rien dans la chaîne de prix ne le
signale — le module de coût fait exactement ce qu'on lui demande.

Ce module ne corrige rien et ne devine aucune quantité. Il nomme ce qui est
invraisemblable pour que l'affichage puisse le dire, et pour que la curation
sache quoi reprendre à la source.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping


#: Familles dont un ingrédient constitue le corps d'un plat. En dessous de
#: quelques grammes, la quantité n'est pas une pincée : c'est une erreur de
#: conversion à l'import. Les familles absentes — épices, herbes, sauces,
#: huiles, levants — s'emploient légitimement au gramme près.
#:
#: « conserves » en est exclue volontairement : la famille mêle des
#: ingrédients de corps (haricots, tomates en boîte) et des condiments
#: employés à la cuillère (purée de chipotle, pâte de cari). Une demi-cuillère
#: à thé de purée de chipotle pèse 3 g et c'est juste — la règle y produisait
#: un faux positif, et un faux positif sur une quantité exacte coûte plus que
#: la détection qu'il apporte. Les formats en boîte, eux, sont déjà lus dans
#: la ligne source (« boîte de 796 ml ») par l'import.
BODY_FAMILIES = frozenset(
    {
        "riz", "cereales", "pates", "farines", "legumineuses", "legumes",
        "alliums", "fruits", "volaille", "boeuf", "veau", "porc", "agneau",
        "poissons", "fruits_de_mer", "oeufs", "produits_laitiers", "fromages",
        "proteines_vegetales", "tomates", "pains",
    }
)

#: Seuil sous lequel une quantité de ces familles est tenue pour fautive. La
#: comparaison reste **stricte**, et c'est une décision mesurée, pas un oubli :
#: rendue inclusive, elle attrapait « 5 tranches de pain » recopié en grammes,
#: mais signalait aussi le zeste d'un citron (5 g, juste) et 5 g de fécule de
#: maïs (2 c. à thé, juste) — deux faux positifs pour un vrai. La revue
#: précédente avait déjà tranché ce genre d'arbitrage en retirant « conserves »
#: des familles de corps : un faux positif sur une valeur juste coûte plus que
#: la détection qu'il apporte. Le pain à 5 g de la salade panzanella reste
#: signalé, par la borne supérieure sur trois de ses autres ingrédients.
MIN_PLAUSIBLE_BODY_QUANTITY = Decimal("5")

#: Quantité maximale plausible par portion, par famille, en unité de base
#: (g ou ml). Un seuil unique ne peut pas trancher : 60 g d'herbes fraîches par
#: personne est absurde, 60 g de viande est une portion d'enfant. Les valeurs
#: sont calées au-dessus du 90e centile observé sur le corpus des 161 recettes
#: et en dessous des cas fautifs connus — 1 100 g de pain au levain et 1 000 g
#: de roquette par portion, 188 g de basilic frais.
#:
#: Une famille absente n'est pas bornée : mieux vaut ne rien dire que de
#: signaler une quantité juste, comme la revue précédente l'a établi en
#: retirant « conserves » des familles de corps.
MAX_PLAUSIBLE_PER_SERVING = {
    "herbes": Decimal("60"),
    "epices": Decimal("30"),
    "noix_graines": Decimal("100"),
    "huiles": Decimal("150"),
    "sauces": Decimal("200"),
    "sucres": Decimal("200"),
    "pains": Decimal("200"),
    "patisserie": Decimal("300"),
    "farines": Decimal("300"),
    "riz": Decimal("300"),
    "pates": Decimal("300"),
    "cereales": Decimal("300"),
    "legumineuses": Decimal("300"),
    "fruits": Decimal("400"),
    "oeufs": Decimal("400"),
    "produits_laitiers": Decimal("400"),
    "fromages": Decimal("400"),
    "proteines_vegetales": Decimal("400"),
    "alliums": Decimal("500"),
    "conserves": Decimal("600"),
    "tomates": Decimal("600"),
    "bouillons": Decimal("600"),
    "legumes": Decimal("600"),
    "agneau": Decimal("700"),
    "boeuf": Decimal("700"),
    "fruits_de_mer": Decimal("700"),
    "poissons": Decimal("700"),
    "porc": Decimal("700"),
    "veau": Decimal("700"),
    "volaille": Decimal("700"),
    "boissons": Decimal("1500"),
}

#: Au-delà, le nombre de portions ne décrit plus un ménage, quelle que soit
#: la preuve : sert de garde-fou de dernier recours.
MAX_PLAUSIBLE_SERVINGS = 60

#: La liste d'unités de rendement qui vivait ici (« boulette », « bouchée »,
#: « ml »…) a été retirée : elle absolvait tout ce qui n'y figurait pas, donc
#: « 2 douzaines » et « 20 boules » passaient. La règle demande maintenant une
#: preuve positive de portions (voir `_yield_proves_servings`), ce qu'aucune
#: énumération de contre-exemples ne pouvait garantir.


@dataclass(frozen=True)
class QualityFlag:
    """Un défaut nommé, avec de quoi le retrouver dans la recette source."""

    kind: str
    subject: str
    detail: str


def review_recipe(recipe: object, canonical_ingredients: Mapping[str, object]) -> tuple[QualityFlag, ...]:
    """Défauts de vraisemblance d'une recette, du plus structurel au plus fin."""
    flags: list[QualityFlag] = []
    servings = int(_field(recipe, "original_servings"))
    tags = _tags(recipe)
    yield_text = str(tags.get("servings_source") or "")
    curated = bool(tags.get("servings_basis"))
    if servings > MAX_PLAUSIBLE_SERVINGS:
        flags.append(
            QualityFlag(
                "implausible_servings",
                str(servings),
                f"{servings} portions déclarées",
            )
        )
    elif (
        not curated
        and _imported(recipe)
        and not _yield_proves_servings(yield_text, servings)
    ):
        # La preuve, pas un seuil : une tourtière à 24 portions est légitime,
        # « 24 bouchées » ne l'est pas. Et l'absence de preuve n'est pas une
        # preuve d'absence de problème : « 2 douzaines » ou « 20 boulettes »
        # échappaient à la règle simplement parce qu'aucun marqueur connu n'y
        # figurait. Le rendement doit dire qu'il compte des portions, sinon la
        # division par portion repose sur une supposition.
        flags.append(
            QualityFlag(
                "yield_not_in_servings",
                yield_text or "(aucun rendement publié)",
                f"rendement publié « {yield_text} » compté comme {servings} portions"
                if yield_text
                else f"aucun rendement publié, {servings} portions supposées",
            )
        )

    seen: dict[str, int] = {}
    for row in _field(recipe, "ingredients"):
        ingredient_id = str(_field(row, "canonical_ingredient_id"))
        seen[ingredient_id] = seen.get(ingredient_id, 0) + 1
    for ingredient_id, count in seen.items():
        if count > 1:
            flags.append(
                QualityFlag(
                    "duplicate_ingredient",
                    ingredient_id,
                    f"compté {count} fois dans la même recette",
                )
            )

    for row in _field(recipe, "ingredients"):
        ingredient_id = str(_field(row, "canonical_ingredient_id"))
        canonical = canonical_ingredients.get(ingredient_id)
        if canonical is None:
            continue
        base_unit = str(_field(canonical, "base_unit"))
        if base_unit not in {"g", "ml"}:
            continue
        family_id = str(_field(canonical, "family_id"))
        required = Decimal(str(_field(row, "qty_fixed_per_batch_base_unit"))) + Decimal(
            str(_field(row, "qty_marginal_per_serving_base_unit"))
        ) * servings
        if (
            family_id in BODY_FAMILIES
            and required < MIN_PLAUSIBLE_BODY_QUANTITY
        ):
            flags.append(
                QualityFlag(
                    "implausible_quantity",
                    ingredient_id,
                    f"{_plain(required)} {base_unit} pour {servings} portions",
                )
            )
            continue
        maximum = MAX_PLAUSIBLE_PER_SERVING.get(family_id)
        if maximum is not None and required / servings > maximum:
            flags.append(
                QualityFlag(
                    "implausible_quantity_per_serving",
                    ingredient_id,
                    f"{_plain(required / servings)} {base_unit} par portion "
                    f"({_plain(required)} {base_unit} pour {servings}), "
                    f"au-delà de {_plain(maximum)} {base_unit} pour la famille "
                    f"« {family_id} »",
                )
            )
    return tuple(flags)


def review_recipes(
    recipes: Iterable[object], canonical_ingredients: Iterable[object]
) -> dict[str, tuple[QualityFlag, ...]]:
    """Défauts par identifiant de recette; une recette saine est absente."""
    catalogue = {
        str(_field(item, "id")): item for item in canonical_ingredients
    }
    result: dict[str, tuple[QualityFlag, ...]] = {}
    for recipe in recipes:
        flags = review_recipe(recipe, catalogue)
        if flags:
            result[str(_field(recipe, "id"))] = flags
    return result


def _yield_proves_servings(text: str, servings: int) -> bool:
    """Le rendement publié atteste-t-il un nombre de portions ?

    Trois preuves acceptées, et rien d'autre : le mot « portion » (ou l'un de
    ses équivalents), ou un nombre nu égal au nombre de portions retenu — le
    détaillant publie alors un champ « portions » sans en répéter l'unité, et
    l'import l'a recopié tel quel.

    Tout le reste est une supposition, y compris l'absence de rendement. C'était
    le trou de la règle précédente : elle ne signalait que les unités connues
    (« bouchée », « boulette »), donc « 2 douzaines » ou « 20 boules » passaient
    faute d'un marqueur dans la liste, et une recette sans rendement du tout
    passait aussi.
    """
    lowered = text.strip().lower()
    if not lowered:
        return False
    if any(word in lowered for word in ("portion", "personne", "serving", "convive")):
        return True
    return lowered.isdigit() and int(lowered) == servings


def _imported(recipe: object) -> bool:
    """Une recette du corpus importé, par opposition au catalogue curé à la main.

    La règle ne s'applique qu'aux premières : les 40 recettes de seed écrites à
    la main n'ont pas de rendement publié à citer, et leur nombre de portions
    est un choix, pas une lecture.
    """
    return bool(_tags(recipe).get("import_origin"))


def _tags(recipe: object) -> Mapping:
    try:
        tags = _field(recipe, "tags")
    except (KeyError, AttributeError):
        return {}
    return tags if isinstance(tags, Mapping) else {}


def _plain(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _field(value: object, name: str):
    return value[name] if isinstance(value, Mapping) else getattr(value, name)
