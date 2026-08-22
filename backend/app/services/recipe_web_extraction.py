"""Une page de recette devient un brouillon, ou refuse en nommant la raison.

Ce module est **pur** : il ne va pas sur le réseau. On lui donne les octets
d'une page déjà chargée et il en tire un brouillon — nom, rendement, temps,
lignes d'ingrédients — puis analyse chaque ligne et cherche l'ingrédient
canonique qu'elle nomme.

**Ce qu'il lit, et pourquoi seulement ça.** Le JSON-LD `schema.org/Recipe`, que
les sites publient pour les moteurs de recherche. C'est une donnée déclarée par
l'éditeur, pas une lecture de mise en page : elle ne casse pas au prochain
changement de gabarit. Mesuré sur deux sites du corpus : bonpourtoi.ca le publie
au complet (13 lignes, rendement, temps), ricardocuisine.com ne publie qu'un
noeud « WebSite » — d'où un refus nommé plutôt qu'une extraction devinée.

**Ce qu'il ne fait pas.** Il ne décide rien. Une ligne sans quantité, une ligne
dont aucun alias ne nomme l'ingrédient : le brouillon le dit, et la décision
reste humaine. C'est la même règle que pour l'appariement canonique → FCÉN :
proposer, jamais rattacher sur une ressemblance.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping

__all__ = [
    "ExtractionRefused",
    "NO_QUANTITY",
    "NO_STRUCTURED_RECIPE",
    "ParsedLine",
    "RecipeDraft",
    "extract_recipe",
    "parse_ingredient_line",
    "resolve_canonical",
]

#: Pourquoi une page n'a pas donné de brouillon.
NO_STRUCTURED_RECIPE = "no_structured_recipe"

#: Pourquoi une ligne n'a pas donné de quantité utilisable.
NO_QUANTITY = "no_quantity"

#: Le vocabulaire d'unités **est celui de l'importateur** de recettes
#: (`scripts/import_cook_recipes.py`), pas un second : c'est lui qui convertit
#: ensuite vers l'unité de base du canon, et deux vocabulaires finiraient par
#: diverger sur une tasse.
_UNITS: dict[str, str] = {
    "ml": "millilitre", "millilitre": "millilitre", "millilitres": "millilitre",
    "l": "litre", "litre": "litre", "litres": "litre",
    "g": "gram", "gramme": "gram", "grammes": "gram",
    "kg": "kilogram", "kilogramme": "kilogram", "kilogrammes": "kilogram",
    "tasse": "cup", "tasses": "cup",
    "c. a soupe": "tablespoon", "c a soupe": "tablespoon",
    "cuillere a soupe": "tablespoon", "cuilleres a soupe": "tablespoon",
    "c. a table": "tablespoon", "c a table": "tablespoon",
    "c. a the": "teaspoon", "c a the": "teaspoon",
    "cuillere a the": "teaspoon", "cuilleres a the": "teaspoon",
    "lb": "pound", "livre": "pound", "livres": "pound",
    "oz": "ounce", "once": "ounce", "onces": "ounce",
    "gousse": "clove", "gousses": "clove",
    "tranche": "slice", "tranches": "slice",
    "branche": "stalk", "branches": "stalk",
    "boite": "can", "boites": "can", "conserve": "can",
    "paquet": "package", "paquets": "package", "sachet": "package",
    "pincee": "pinch", "pincees": "pinch",
    "feuille": "leaf", "feuilles": "leaf",
    "bouquet": "bunch", "bouquets": "bunch",
}

#: Les fractions que les pages écrivent en un seul caractère.
_FRACTIONS = {
    "1/2": Decimal("0.5"), "1/4": Decimal("0.25"), "3/4": Decimal("0.75"),
}
_FRACTIONS.update({
    "½": Decimal("0.5"), "¼": Decimal("0.25"), "¾": Decimal("0.75"),
    "⅓": Decimal(1) / Decimal(3), "⅔": Decimal(2) / Decimal(3),
    "⅛": Decimal("0.125"), "⅜": Decimal("0.375"),
    "⅝": Decimal("0.625"), "⅞": Decimal("0.875"),
})

_NUMBER = re.compile(r"(\d+(?:[.,]\d+)?)")
_ISO_DURATION = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?", re.IGNORECASE)


class ExtractionRefused(ValueError):
    """La page n'a pas donné de recette, et le refus porte sa raison.

    Nommée pour que l'appelant distingue « cette page ne publie pas de recette
    structurée » — un autre chemin est nécessaire — de « la page est illisible ».
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class RecipeDraft:
    """Ce qu'une page déclare : rien de plus, rien de deviné."""

    name: str
    servings: int | None
    prep_time_h: Decimal | None
    cook_time_h: Decimal | None
    lines: tuple[str, ...]
    source_url: str


@dataclass(frozen=True)
class ParsedLine:
    """Une ligne d'ingrédient lue : quantité, unité, libellé, et ce qui manque."""

    raw: str
    label: str
    quantity: Decimal | None
    unit: str | None
    reason: str | None
    #: Toutes les mesures que la ligne publie, dans l'ordre de lecture. Une
    #: page écrit « 2 c. à soupe (30 ml (30 g)) » : le volume ET la masse. Qui
    #: connaît l'unité de base du canon choisit la bonne, et n'a alors aucune
    #: conversion à inventer.
    candidates: tuple[tuple[Decimal, str], ...] = ()


def extract_recipe(html: bytes, source_url: str) -> RecipeDraft:
    """Brouillon depuis le JSON-LD `schema.org/Recipe` de la page."""
    text = html.decode("utf-8", "replace")
    for block in re.findall(
        r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", text, re.S
    ):
        for node in _nodes(block):
            if "Recipe" not in str(node.get("@type", "")):
                continue
            lines = tuple(
                str(line).strip()
                for line in (node.get("recipeIngredient") or [])
                if str(line).strip()
            )
            if not lines:
                continue
            return RecipeDraft(
                name=str(node.get("name") or "").strip(),
                servings=_servings(node.get("recipeYield")),
                prep_time_h=_hours(node.get("prepTime")),
                cook_time_h=_hours(node.get("cookTime")),
                lines=lines,
                source_url=source_url,
            )
    raise ExtractionRefused(
        NO_STRUCTURED_RECIPE,
        "La page ne publie pas de recette structurée (JSON-LD "
        "schema.org/Recipe avec des lignes d'ingrédients). Les lignes existent "
        "peut-être dans la mise en page, mais les lire là serait deviner : un "
        "autre chemin est nécessaire pour cette page.",
    )


def parse_ingredient_line(line: str) -> ParsedLine:
    """Quantité, unité et libellé d'une ligne, ou la raison de leur absence.

    **La mesure métrique gagne.** Les pages québécoises écrivent « ½ tasse
    (125 ml) » : la mesure d'ustensile devant, la métrique derrière. La seconde
    ne dépend pas de la taille d'une tasse, donc c'est celle qu'on retient. Quand
    une parenthèse en porte deux — « 30 ml (30 g) » — le millilitre passe devant
    le gramme : c'est le volume que la recette mesure, et la conversion vers la
    masse est le travail du canon, avec sa densité curée.
    """
    label, tail = _split_label(line)
    label = _clean(label)
    candidates = _measurements(tail or line)
    if not candidates:
        return ParsedLine(line, label, None, None, NO_QUANTITY, ())
    found = tuple(candidates)
    for wanted in ("millilitre", "litre", "gram", "kilogram"):
        for quantity, unit in found:
            if unit == wanted:
                return ParsedLine(line, label, quantity, unit, None, found)
    quantity, unit = found[0]
    return ParsedLine(line, label, quantity, unit, None, found)


def resolve_canonical(label: str, aliases: Mapping[str, str]) -> str | None:
    """L'ingrédient canonique que ce libellé nomme, ou `None`.

    Deux stratégies, dans cet ordre : l'alias exact, puis **l'alias le plus long
    contenu** dans le libellé. La seconde existe parce qu'une page écrit
    « beurre fondu tiède » là où le canon dit « beurre » — et elle prend le plus
    long pour que « beurre non salé » ne soit jamais résolu en « beurre ». Aucune
    ressemblance approximative : un libellé qu'aucun alias ne nomme reste sans
    réponse, et c'est une décision humaine.
    """
    folded = _fold(label)
    exact = aliases.get(folded)
    if exact is not None:
        return exact
    singular = _singularise(folded)
    best: tuple[int, str] | None = None
    for alias, ingredient_id in aliases.items():
        candidate = _singularise(_fold(alias))
        if len(candidate) < 4 or not _contains_words(singular, candidate):
            continue
        if best is None or len(candidate) > best[0]:
            best = (len(candidate), ingredient_id)
    return best[1] if best else None


#: Une quantité commence par un chiffre, une fraction, ou « au goût ».
_QUANTITY_HEAD = re.compile(r"^\s*(?:\d|[½¼¾⅓⅔⅛⅜⅝⅞]|au go)", re.IGNORECASE)


def _split_label(line: str) -> tuple[str, str]:
    """Sépare le libellé de la quantité, à la DERNIÈRE virgule utile.

    « Lait 3,25 %, 750 ml » porte deux virgules : celle du nombre décimal et
    celle du format. Couper à la première donnait le libellé « lait 3 », qui se
    résolvait vers un ingrédient voisin — assez proche pour n'alerter personne,
    assez faux pour changer la valeur nutritive.
    """
    best: tuple[str, str] | None = None
    for index, character in enumerate(line):
        if character != ",":
            continue
        # Une virgule décimale est entre deux chiffres : « 2,5 » n'est pas une
        # frontière entre le libellé et la quantité.
        before = line[index - 1] if index else ""
        after = line[index + 1] if index + 1 < len(line) else ""
        if before.isdigit() and after.isdigit():
            continue
        tail = line[index + 1:]
        if _QUANTITY_HEAD.match(tail):
            best = (line[:index], tail)
    if best is None:
        head, _, tail = line.partition(",")
        return head, tail
    return best


def _singularise(text: str) -> str:
    """Ramène chaque mot au singulier, grossièrement mais symétriquement.

    Le canon écrit « clou de girofle », les pages écrivent « clous de girofle
    entiers ». Retirer un « s » ou un « x » final des deux côtés suffit à les
    faire se rencontrer, et le fait des deux côtés évite d'inventer une règle
    qui ne marcherait que dans un sens. Les mots de trois lettres ou moins sont
    laissés tels quels : « riz » n'est pas un pluriel.
    """
    words = []
    for word in text.split():
        words.append(word[:-1] if len(word) > 3 and word[-1] in "sx" else word)
    return " ".join(words)


def _nodes(block: str) -> list[dict]:
    try:
        data = json.loads(block)
    except json.JSONDecodeError:
        return []
    items = data if isinstance(data, list) else [data]
    found: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        graph = item.get("@graph")
        found.extend(
            node for node in (graph if isinstance(graph, list) else [item])
            if isinstance(node, dict)
        )
    return found


def _measurements(text: str) -> list[tuple[Decimal, str]]:
    """Les mesures lisibles d'un fragment : parenthèses d'abord, puis le reste.

    L'ordre compte : c'est lui qui fait gagner « (125 ml) » sur « ½ tasse ».
    """
    found: list[tuple[Decimal, str]] = []
    fragments = re.findall(r"\(([^()]*(?:\([^()]*\))?[^()]*)\)", text) + [text]
    for fragment in fragments:
        for pair in _measurement_pairs(fragment):
            if pair not in found:
                found.append(pair)
    return found


def _measurement_pairs(fragment: str) -> list[tuple[Decimal, str]]:
    pairs: list[tuple[Decimal, str]] = []
    for match in re.finditer(
        r"(\d+(?:[.,]\d+)?|[½¼¾⅓⅔⅛⅜⅝⅞])\s*([^\d(),]*)", fragment
    ):
        quantity = _quantity(match.group(1))
        if quantity is None:
            continue
        unit = _unit(match.group(2))
        if unit is None:
            # Un nombre suivi d'un mot qui n'est pas une unité connue dénombre
            # des articles : « 12 ailes », « 2 oignons ».
            unit = "piece" if _fold(match.group(2)).strip(" .") else None
        if unit is not None:
            pairs.append((quantity, unit))
    return pairs


def _quantity(text: str) -> Decimal | None:
    if text in _FRACTIONS:
        return _FRACTIONS[text]
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None


def _unit(text: str) -> str | None:
    folded = _fold(text).strip(" .")
    if not folded:
        return None
    words = folded.split()
    for length in range(min(4, len(words)), 0, -1):
        candidate = " ".join(words[:length])
        for form in (candidate, candidate.rstrip(".")):
            if form in _UNITS:
                return _UNITS[form]
    return None


def _servings(value: object) -> int | None:
    if value is None:
        return None
    first = value[0] if isinstance(value, list) and value else value
    match = _NUMBER.search(str(first))
    return int(Decimal(match.group(1).replace(",", "."))) if match else None


def _hours(value: object) -> Decimal | None:
    if not value:
        return None
    match = _ISO_DURATION.fullmatch(str(value).strip())
    if match is None:
        return None
    total = Decimal(match.group(1) or 0) + Decimal(match.group(2) or 0) / 60
    return total.quantize(Decimal("0.01")) if total else None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _fold(text: str) -> str:
    lowered = unicodedata.normalize("NFD", text.replace("’", "'").lower())
    return "".join(c for c in lowered if unicodedata.category(c) != "Mn")


def _contains_words(haystack: str, needle: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(needle)}(?![a-z])", haystack) is not None


#: La dimension de chaque unité du vocabulaire. Elle sert à refuser une ligne
#: que le canon ne sait pas convertir : « 22,5 ml d'ail » vise un ingrédient qui
#: se compte à la gousse, et inventer la conversion serait pire que la refuser.
_DIMENSIONS = {
    "millilitre": "volume", "litre": "volume", "cup": "volume",
    "tablespoon": "volume", "teaspoon": "volume",
    "gram": "mass", "kilogram": "mass", "pound": "mass", "ounce": "mass",
}


def dimension_of(unit: str | None) -> str | None:
    """« volume », « mass », « count », ou `None` si l'unité est inconnue."""
    if unit is None:
        return None
    if unit in _DIMENSIONS:
        return _DIMENSIONS[unit]
    # « piece » ne figure pas dans le vocabulaire d'entrée : c'est ce que le
    # parseur écrit quand un nombre est suivi d'un mot qui n'est pas une unité
    # (« 12 ailes »). Il dénombre donc, comme les autres unités d'articles.
    return "count" if unit == "piece" or unit in set(_UNITS.values()) else None
