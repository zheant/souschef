"""Dériver du FCÉN une masse par unité et une densité — ou refuser de le faire.

Module pur. Il lit les mesures domestiques du fichier fédéral
(``Measure_Weight_Conversion``, type ``6`` : mesures de service) et en tire deux
faits que le calcul nutritionnel réclame sans pouvoir les inventer :

- **la masse d'une unité**, pour les ingrédients qui se comptent (« 1 gousse
  d'ail »). ``units.convert_qty`` refuse compte↔masse et continue de le
  refuser : c'est une donnée de curation, pas une conversion.
- **la densité**, pour les ingrédients qui se mesurent en volume.

**Le piège de la densité de tassement.** Le FCÉN publie « 250 ml de mozzarella
râpée = 113 g ». Le rapport donne 0,45 g/ml, et ce n'est pas une densité : c'est
la façon dont des filaments occupent un contenant. L'appliquer à une recette qui
demande 200 ml de lait donnerait 90 g au lieu de 206. Le module refuse donc
toute mesure dont le libellé décrit un solide découpé ou tassé, et refuse aussi
les rapports qui sortent de la bande des liquides de cuisine ou qui ne
s'accordent pas entre eux — deux volumes du même aliment doivent donner la même
densité, sinon ce n'en est pas une.

Aucune valeur n'est écrite par ce module : il rend des propositions portant leur
provenance, à appliquer par une décision explicite.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Sequence

__all__ = [
    "AMBIGUOUS_COUNT_MEASURES",
    "INCONSISTENT_RATIOS",
    "MeasureWeight",
    "NOT_POURABLE",
    "NO_COUNT_MEASURE",
    "NO_VOLUME_MEASURE",
    "OUT_OF_LIQUID_RANGE",
    "SERVING_MEASURE_TYPE",
    "UnitMassProposal",
    "DensityProposal",
    "propose_density",
    "propose_unit_mass",
]

#: Mesures utilisables : celles définies pour le service. ``3`` décrit une
#: portion non comestible et ``9`` un rendement de cuisson.
SERVING_MEASURE_TYPE = "6"

NO_COUNT_MEASURE = "no_count_measure"
AMBIGUOUS_COUNT_MEASURES = "ambiguous_count_measures"
NO_VOLUME_MEASURE = "no_volume_measure"
NOT_POURABLE = "not_pourable"
OUT_OF_LIQUID_RANGE = "out_of_liquid_range"
INCONSISTENT_RATIOS = "inconsistent_ratios"

#: Bande des liquides de cuisine, bornes comprises : huile 0,91, eau 1,00,
#: bouillon 1,10, sirop d'érable 1,32, miel 1,42. Hors de cette bande, le
#: rapport décrit un tassement, pas un écoulement.
_MIN_DENSITY = Decimal("0.7")
_MAX_DENSITY = Decimal("1.5")

#: Écart relatif toléré entre deux volumes du même aliment. Une densité est une
#: constante : 5 ml et 250 ml doivent donner le même rapport. Le même seuil
#: borne l'écart admis entre deux mesures de compte candidates.
_MAX_SPREAD = Decimal("0.05")

#: Ligatures que la décomposition Unicode ne défait pas. Le fichier fédéral
#: écrit « 1 œuf jumbo » et « 1 oeufs large (gros) » dans le même aliment :
#: sans réduction, le premier libellé seul répondait au canon « Œuf de calibre
#: gros », et 66,06 g étaient proposés pour un œuf de 52,61 g.
_LIGATURES = {"œ": "oe", "Œ": "oe", "æ": "ae", "Æ": "ae"}

#: Libellés qui décrivent un solide découpé, râpé ou tassé. Le rapport
#: grammes/millilitre y mesure l'entassement.
_PACKED_WORDS = (
    "rape", "hache", "tranche", "cube", "emiette", "tasse", "morceau",
    "grain", "moitie", "quartier", "feuille", "flocon", "lanieres", "lanière",
    "tronconne", "rondelle", "julienne", "des", "entier", "entiere", "filet",
    "branche", "gousse", "bouquet", "poignee", "boule", "tete",
    # Un état aéré : 100 ml de crème fouettée pèsent la moitié de 100 ml de
    # crème. C'est de l'air mesuré, exactement comme le tassement du râpé.
    "fouette",
)

#: « 250 ml liquide (donne 2 tasses fouettée) » — ce qui suit « donne » dit ce
#: que la mesure *produit*, pas ce qu'elle mesure. Sans cette coupe, le mot
#: « tasses » du rendement écartait la seule mesure d'écoulement publiée.
_YIELD_CLAUSE = re.compile(r"\(\s*donne\b[^)]*\)?", re.IGNORECASE)

#: « 250 ml », « 125 ml purée », « 15 ml » — un volume explicite en tête.
_VOLUME_ML = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*ml\b")

#: « 1 gousse », « 1 fruit », « 1 moyen (10.5cm long) » — un compte en tête.
_COUNT = re.compile(r"^(\d+(?:[.,]\d+)?)\s+(?!ml\b)(\S.*)$")

_THREE = Decimal("0.001")


@dataclass(frozen=True)
class MeasureWeight:
    """Une ligne de ``Measure_Weight_Conversion``, telle qu'importée."""

    food_code: str
    measure_type_code: str
    measure_code: str
    description: str | None
    grams: Decimal


@dataclass(frozen=True)
class UnitMassProposal:
    ingredient_id: str
    food_code: str
    grams_per_unit: Decimal | None
    measure_description: str | None
    provenance: str
    reason: str | None = None


@dataclass(frozen=True)
class DensityProposal:
    ingredient_id: str
    food_code: str
    density_g_per_ml: Decimal | None
    provenance: str
    reason: str | None = None
    #: Mesures examinées, pour que le refus soit vérifiable sans rejouer.
    examined: tuple[str, ...] = ()


def propose_unit_mass(
    ingredient_id: str,
    ingredient_name: str,
    food_code: str,
    food_name: str,
    measures: Iterable[MeasureWeight],
) -> UnitMassProposal:
    """Masse d'une unité, prise sur la mesure que l'ingrédient nomme lui-même.

    Une mesure de compte est un libellé qui commence par un nombre suivi d'autre
    chose qu'un volume : « 1 gousse », « 1 fruit », « 1 moyen (10,5 cm long) ».
    L'aliment « Ail, cru » en publie deux — « 1 gousse » (3 g) et « 1 bulbe »
    (24 g) — et rien dans le fichier fédéral ne dit laquelle est l'unité de la
    recette. Le canon le dit : l'ingrédient s'appelle « Gousse d'ail ». Le
    libellé qui partage un mot avec lui passe donc devant, et un facteur huit
    ne se joue pas sur la longueur d'une étiquette.
    """
    counted = [
        (measure, ratio)
        for measure, ratio in (
            (measure, _count_of(measure)) for measure in _servings(measures)
        )
        if ratio is not None and ratio > 0
    ]
    if not counted:
        return UnitMassProposal(
            ingredient_id,
            food_code,
            None,
            None,
            f"FCÉN 2026, aliment {food_code} « {food_name} » : aucune mesure "
            "de service exprimée en unités.",
            NO_COUNT_MEASURE,
        )
    named = _fold(ingredient_name).split()
    preferred = [
        row for row in counted if _shares_word(row[0].description, named)
    ] or counted
    # Plusieurs mesures de compte peuvent nommer l'ingrédient sans décrire la
    # même chose : l'aliment 125 publie « 1 oeufs large (gros) » (52,61 g),
    # « 1 oeuf extra gros » (58,09 g) et « 1 œuf jumbo » (66,06 g). Départager
    # au plus court libellé proposait le jumbo pour un gros — 26 % de trop.
    # Le calibre d'un œuf est un jugement, pas une longueur d'étiquette : le
    # module refuse et publie les candidats.
    unit_masses = [_round(row[0].grams / row[1]) for row in preferred]
    if len(preferred) > 1 and max(unit_masses) - min(unit_masses) > max(
        unit_masses
    ) * _MAX_SPREAD:
        return UnitMassProposal(
            ingredient_id,
            food_code,
            None,
            None,
            f"FCÉN 2026, aliment {food_code} « {food_name} » : "
            f"{len(preferred)} mesures de compte s'accordent avec "
            f"{ingredient_name!r} sans s'accorder entre elles ("
            + "; ".join(
                f"{row[0].description} = {row[0].grams} g" for row in preferred
            )
            + "). Le calibre est un jugement, pas une dérivation.",
            AMBIGUOUS_COUNT_MEASURES,
        )
    measure, count = min(
        preferred,
        key=lambda row: (
            len(row[0].description or ""),
            row[0].measure_code,
        ),
    )
    grams = _round(measure.grams / count)
    return UnitMassProposal(
        ingredient_id,
        food_code,
        grams,
        measure.description,
        f"FCÉN 2026, aliment {food_code} « {food_name} » : "
        f"{measure.description} = {measure.grams} g, soit {grams} g par unité.",
    )


def propose_density(
    ingredient_id: str,
    food_code: str,
    food_name: str,
    measures: Iterable[MeasureWeight],
) -> DensityProposal:
    """Densité en g/ml, ou refus motivé — jamais un rapport de tassement."""
    volumetric = [
        (measure, millilitres)
        for measure, millilitres in (
            (measure, _millilitres_of(measure)) for measure in _servings(measures)
        )
        if millilitres is not None and millilitres > 0
    ]
    examined = tuple(
        f"{measure.description} = {measure.grams} g"
        for measure, _ml in volumetric
    )
    if not volumetric:
        return DensityProposal(
            ingredient_id,
            food_code,
            None,
            f"FCÉN 2026, aliment {food_code} « {food_name} » : aucune mesure "
            "de service exprimée en millilitres.",
            NO_VOLUME_MEASURE,
        )
    # Une mesure tassée ou aérée s'écarte, elle ne disqualifie pas l'aliment :
    # le fichier publie « 250 ml liquide » et « 250 ml fouetté » pour la même
    # crème. Refuser l'aliment laissait une mesure d'entassement l'emporter sur
    # trois mesures d'écoulement qui s'accordent. Un aliment dont *toutes* les
    # mesures sont tassées — le fromage râpé — reste refusé.
    packed = [
        measure.description
        for measure, _ml in volumetric
        if _describes_packed_solid(measure.description)
    ]
    pourable = [
        (measure, millilitres)
        for measure, millilitres in volumetric
        if not _describes_packed_solid(measure.description)
    ]
    if not pourable:
        return DensityProposal(
            ingredient_id,
            food_code,
            None,
            f"FCÉN 2026, aliment {food_code} « {food_name} » : les mesures en "
            f"millilitres décrivent un solide découpé ou tassé ({packed[0]}). "
            "Le rapport mesurerait l'entassement, pas l'écoulement.",
            NOT_POURABLE,
            examined,
        )
    volumetric = pourable
    ratios = [_round(measure.grams / ml) for measure, ml in volumetric]
    lowest, highest = min(ratios), max(ratios)
    if highest - lowest > highest * _MAX_SPREAD:
        return DensityProposal(
            ingredient_id,
            food_code,
            None,
            f"FCÉN 2026, aliment {food_code} « {food_name} » : les mesures ne "
            f"s'accordent pas ({lowest} à {highest} g/ml). Une densité est une "
            "constante; cet écart dit que le volume dépend de la découpe.",
            INCONSISTENT_RATIOS,
            examined,
        )
    # Le plus grand volume publié porte le moins d'arrondi fédéral.
    largest, millilitres = max(volumetric, key=lambda row: row[1])
    density = _round(largest.grams / millilitres)
    if not _MIN_DENSITY <= density <= _MAX_DENSITY:
        return DensityProposal(
            ingredient_id,
            food_code,
            None,
            f"FCÉN 2026, aliment {food_code} « {food_name} » : rapport de "
            f"{density} g/ml, hors de la bande des liquides de cuisine "
            f"({_MIN_DENSITY} à {_MAX_DENSITY}).",
            OUT_OF_LIQUID_RANGE,
            examined,
        )
    return DensityProposal(
        ingredient_id,
        food_code,
        density,
        f"FCÉN 2026, aliment {food_code} « {food_name} » : "
        f"{largest.description} = {largest.grams} g, soit {density} g/ml."
        + (
            f" Mesures tassées ou aérées écartées : {', '.join(packed)}."
            if packed
            else ""
        ),
        None,
        examined,
    )


def _servings(measures: Iterable[MeasureWeight]) -> list[MeasureWeight]:
    return [
        measure
        for measure in measures
        if measure.measure_type_code == SERVING_MEASURE_TYPE and measure.grams > 0
    ]


def _millilitres_of(measure: MeasureWeight) -> Decimal | None:
    found = _VOLUME_ML.search(_fold(measure.description or ""))
    if found is None:
        return None
    return Decimal(found.group(1).replace(",", "."))


def _count_of(measure: MeasureWeight) -> Decimal | None:
    text = _fold(measure.description or "").strip()
    if _VOLUME_ML.search(text) is not None:
        return None
    found = _COUNT.match(text)
    if found is None:
        return None
    # « 0.5g » n'est pas un compte : c'est une masse déguisée en libellé.
    if re.match(r"^\d+(?:[.,]\d+)?\s*g\b", text):
        return None
    return Decimal(found.group(1).replace(",", "."))


def _shares_word(description: str | None, named: Sequence[str]) -> bool:
    words = _fold(description or "").replace("(", " ").replace(")", " ").split()
    return any(
        word == other or (len(word) >= 4 and other.startswith(word))
        for word in words
        for other in named
    )


def _describes_packed_solid(description: str | None) -> bool:
    measured = _YIELD_CLAUSE.sub(" ", description or "")
    words = _fold(measured).replace("(", " ").replace(")", " ").split()
    return any(
        word.startswith(packed) for word in words for packed in _PACKED_WORDS
    )


def _fold(text: str) -> str:
    for ligature, plain in _LIGATURES.items():
        text = text.replace(ligature, plain)
    return "".join(
        character
        for character in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(character) != "Mn"
    )


def _round(value: Decimal) -> Decimal:
    return value.quantize(_THREE, rounding=ROUND_HALF_UP)
