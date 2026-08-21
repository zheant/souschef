"""Proposer des aliments FCÉN pour un ingrédient canonique — jamais décider.

Module pur : il ne lit ni fichiers ni base de données, et il ne rattache rien.
Il rend, par ingrédient, une courte liste de candidats classés et une liste de
rejets **motivés**. La décision reste humaine et passe par l'action
``attach_existing`` du pipeline de curation, qui la journalise. C'est la règle
du dépôt : aucun rattachement automatique sur ressemblance.

**Pourquoi des jetons et non la chaîne entière.** La similarité de chaînes
existante (`normalize_label`/`label_similarity`) manque les appariements dont le
nom fédéral commence ailleurs : « Ketchup » contre « Tomates, ketchup
(catsup) », « Parmesan » contre « Fromage parmesan, pâte dure », « Courgette »
contre « Courge d'été, courgette (zucchini), crue », « Poireau » contre
« Poireaux (bulbe et portion inférieure), crus ». Le mot cherché est là, mais
il pèse peu dans la chaîne entière. La recherche par jetons le retrouve.

**Ce que le classement encode**, dans cet ordre de poids :

1. la **couverture** — combien des mots significatifs du nom canonique se
   retrouvent dans le nom fédéral ;
2. la **famille** du canon, qui dit ce que le nom seul ne dit pas (« Parmesan »
   ne dit pas qu'on cherche un fromage; sa famille le dit) ;
3. l'**état cru**, parce que le projet suppose des quantités d'achat crues ;
4. une pénalité par mot fédéral que le canon ne nomme pas — un nom fédéral plus
   bavard décrit un aliment plus spécifique que celui qu'on cherche ;
5. une pénalité de **forme dérivée** : un jus, une poudre, une soupe, une farine
   que le nom canonique ne mentionne pas décrivent une transformation, pas
   l'ingrédient (« Tomate, jus, conserve » pour une tomate en conserve).

**Deux rejets francs**, parce qu'ils ne sont pas une question de degré :

- ``cooked_or_prepared_form`` — le candidat porte une marque de cuisson ou de
  préparation que le nom canonique ne porte pas (« Oignon, bouilli, égoutté »
  pour un oignon jaune). La cuisson déplace l'eau et le gras : ce n'est pas le
  même aliment par 100 g.
- ``composite_dish`` — aucun mot du nom canonique n'apparaît dans les deux
  premiers segments du nom fédéral. Le FCÉN nomme du général au particulier :
  un ingrédient cité au troisième segment est un ingrédient *de* la préparation
  nommée devant. C'est le faux positif type — l'huile appariée à « Pomme de
  terre, frite, congelée, préparée au restaurant avec de l'huile végétale », le
  sirop d'érable apparié à « Crêpe, nature, faite maison avec beurre et sirop
  d'érable ».

Les rejets sont **publiés avec leur motif**, jamais effacés : un curateur doit
pouvoir constater qu'un aliment a été écarté, et pourquoi.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

__all__ = [
    "COMPOSITE_DISH",
    "COOKED_OR_PREPARED_FORM",
    "MatchCandidate",
    "MatchFood",
    "MatchProposal",
    "MatchRejection",
    "MatchTarget",
    "propose_matches",
]

COOKED_OR_PREPARED_FORM = "cooked_or_prepared_form"
COMPOSITE_DISH = "composite_dish"

#: Trois lettres, pas quatre : « riz », « ail », « sel », « eau », « vin »,
#: « jus » sont des aliments à part entière. Mesuré sur le corpus réel, le
#: seuil à quatre laissait « riz_non_precise » et « riz_arborio » sans aucun
#: candidat, faute de pouvoir chercher le mot « riz ». Le bruit des mots courts
#: est écarté par la liste ci-dessous, pas par leur longueur.
_MIN_WORD = 3

#: Mots vides pour un appariement d'aliment. Trois familles : les mots de
#: fonction, les mots de présentation, et les mots de calibre — « Œuf de
#: calibre gros » cherchait « gros » et trouvait « Porc, morceau de gros, gras
#: de dos, cru », à 812 kcal/100 g.
_STOP_WORDS = frozenset(
    {
        "aux", "les", "des", "une", "non", "sur", "par", "son", "ses", "est",
        "que", "qui", "pas", "ces", "cet", "ils", "sont", "avec", "sans",
        "dans", "pour", "tous", "toutes", "tout", "type", "types", "autre",
        "autres", "divers", "diverses", "plus", "moins", "leur", "leurs",
        "cette", "elle", "ajoute", "ajoutee", "ajoutes", "ajoutees", "inclus",
        "incluant", "portion", "portions", "environ", "ordinaire", "nature",
        "naturel", "naturelle", "commercial", "commerciale", "commerciales",
        "commerciaux", "maison", "faite", "fait", "prepare", "preparee",
        "prepares", "preparees",
        "calibre", "gros", "grosse", "grosses", "moyen", "moyenne", "moyens",
        "grand", "grande", "petit", "petite", "petits", "petites",
        "variete", "varietes",
    }
)

#: Mots de nom de famille qui ne désignent aucun aliment. Sans ce filtre, la
#: famille « Produits laitiers » appariait « Crème 35 % » à « Fromage, produit
#: de fromage à la crème » sur le seul mot « produit ».
_GENERIC_FAMILY_WORDS = frozenset(
    {
        "produits", "produit", "transformees", "transformes", "matieres",
        "grasses", "ingredients", "assaisonnements", "plats", "divers",
        "cuisine", "conserves",
    }
)

#: Marques de cuisson ou de préparation. Un candidat qui en porte une absente
#: du nom canonique est rejeté : par 100 g, une carotte bouillie n'est pas une
#: carotte crue.
#:
#: La congélation n'y figure pas : le FCÉN écrit « Oeuf, poule, entier, frais
#: ou congelé, cru », qui est un état d'achat, pas une cuisson. La traiter comme
#: une préparation rejetait l'œuf de poule et laissait l'œuf de cane en tête,
#: à 186 kcal/100 g.
_COOKED_MARKERS = (
    "bouilli", "saute", "frit", "grille", "roti", "cuit", "mijote", "pane",
    "panne", "deshydrate", "lyophilise", "braise", "poche", "rechauffe",
    "blanchi", "gratine", "farci", "confit", "condense", "reconstitue",
)

#: Marques d'état cru — l'hypothèse d'appariement du projet.
_RAW_MARKERS = ("cru", "crue", "crus", "crues")

#: Transformations et préparations qui font un autre aliment quand le canon ne
#: les nomme pas. Deux familles : les dérivés d'un aliment (« Tomate, jus,
#: conserve » pour une tomate en conserve) et les préparations qui contiennent
#: l'ingrédient (« Biscuit, beurre, Petit Beurre » pour du beurre — le mot est
#: en deuxième segment, donc le rejet de plat composé ne le voit pas).
#:
#: « Confiseries » et « Vinaigrette » n'y sont pas : le FCÉN y range le sirop
#: d'érable et la mayonnaise, qui sont les bonnes réponses.
_DERIVED_FORMS = (
    "jus", "soupe", "poudre", "farine", "fecule", "sirop", "sauce", "creme",
    "boisson", "huile", "beurre", "croustille",
    "biscuit", "gateau", "craquelin", "beigne", "bonbon", "brioche", "muffin",
    "tablette", "tartelette", "pizza", "sandwich", "met", "plat", "aliment",
)

_COVERAGE_WEIGHT = Decimal("10")
#: Le mot de tête du nom fédéral désigne l'aliment; les suivants le
#: qualifient. « Veau de lait » contient « lait » sans être du lait, et il
#: gagnait contre « Lait, 3,25 % M.G. » grâce à sa mention « cru ». Faire
#: répondre les têtes entre elles est le signal le plus fort du classement.
_HEAD_MATCH_BONUS = Decimal("4")
_FAMILY_BONUS = Decimal("2")
#: L'état cru ne départage plus que des égalités : les formes cuites sont
#: rejetées, pas classées. Un bonus fort faisait gagner « Veau de lait, cru »
#: contre le lait.
#:
#: Il reste un cas que ce poids ne règle pas et qu'il ne faut pas prétendre
#: réglé : « Melon, miel (honeydew), cru » (36 kcal) passe encore devant
#: « Confiseries, miel, filtre ou extrait » (304 kcal) pour l'ingrédient
#: « Miel ». Les deux noms portent le mot, aux mêmes places, et rien de lexical
#: ne dit que le melon est un fruit et le miel un sucre. Le bon aliment est
#: dans les cinq candidats; le premier est faux d'un facteur 8.
_RAW_BONUS = Decimal("0.5")
#: Un mot de trop dans le **premier** segment change l'aliment (« Lait de
#: poule » n'est pas du lait). Un mot de trop dans les segments suivants ne
#: fait que le préciser (« Lait, liquide, 3,25 % M.G. » reste du lait). Une
#: pénalité uniforme faisait donc gagner le nom court et faux contre le nom
#: long et juste : le lait de poule devant le lait, le « Riz espagnol » devant
#: le riz blanc à grain long.
_EXTRA_FIRST_SEGMENT_PENALTY = Decimal("0.6")
_EXTRA_WORD_PENALTY = Decimal("0.1")
_DERIVED_FORM_PENALTY = Decimal("5")

#: Segments du nom fédéral où un mot du canon doit apparaître. Le FCÉN nomme du
#: général au particulier : au-delà du deuxième segment, l'ingrédient cité est
#: un ingrédient de la préparation, pas l'aliment décrit.
_HEAD_SEGMENT_LIMIT = 2

#: Groupes entre parenthèses. Le FCÉN y met les synonymes de l'aliment, où que
#: la parenthèse tombe dans le nom : « (cassonade) », « (catsup) »,
#: « (zucchini) », « (spaghetti, macaroni) ». Ils comptent donc comme zone de
#: tête, pas comme un ingrédient de plus.
_PARENTHESES = re.compile(r"\(([^)]*)\)")


@dataclass(frozen=True)
class MatchTarget:
    """Un ingrédient canonique à apparier, et ce qui rend l'affaire urgente."""

    ingredient_id: str
    name: str
    family_name: str | None
    base_unit: str
    blocked_recipes: int = 0
    #: Aliments FCÉN déjà rattachés. Le manifeste les répète pour qu'un
    #: ingrédient ambigu se relise avec ses prétendants sous les yeux.
    attached_food_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchFood:
    food_code: str
    name: str
    group: str
    kcal_per_100g: Decimal | None = None


@dataclass(frozen=True)
class MatchCandidate:
    food_code: str
    food_name: str
    group: str
    kcal_per_100g: Decimal | None
    score: Decimal
    signals: tuple[str, ...]


@dataclass(frozen=True)
class MatchRejection:
    food_code: str
    food_name: str
    reason: str


@dataclass(frozen=True)
class MatchProposal:
    ingredient_id: str
    ingredient_name: str
    family_name: str | None
    base_unit: str
    blocked_recipes: int
    attached_food_codes: tuple[str, ...]
    candidates: tuple[MatchCandidate, ...]
    rejected: tuple[MatchRejection, ...]

    def as_dict(self) -> dict:
        return asdict(self)


def propose_matches(
    targets: Iterable[MatchTarget],
    foods: Iterable[MatchFood],
    *,
    limit: int = 5,
    rejected_limit: int = 5,
) -> tuple[MatchProposal, ...]:
    """Rend une proposition par ingrédient, la plus bloquante d'abord."""
    indexed = tuple(_IndexedFood(food) for food in foods)
    # Index par radical de quatre lettres : deux mots qui se répondent au
    # pluriel partagent forcément ce préfixe, puisqu'un mot plus court que
    # quatre lettres n'entre pas dans l'index. Un balayage complet par mot
    # cherché coûtait 5 millions de comparaisons sur le corpus réel.
    by_prefix: dict[str, dict[str, list[_IndexedFood]]] = {}
    for food in indexed:
        for word in food.words:
            bucket = by_prefix.setdefault(word[:_MIN_WORD], {})
            bucket.setdefault(word, []).append(food)

    proposals = [
        _propose(target, by_prefix, limit=limit, rejected_limit=rejected_limit)
        for target in targets
    ]
    # Classement par effet, puis par identifiant : deux exécutions rendent le
    # même manifeste, donc deux décisions citent la même proposition.
    return tuple(
        sorted(
            proposals,
            key=lambda row: (-row.blocked_recipes, row.ingredient_id),
        )
    )


class _IndexedFood:
    """Aliment FCÉN avec ses mots et ses segments, calculés une seule fois."""

    __slots__ = ("food", "words", "all_words", "segment_words", "head_zone")

    def __init__(self, food: MatchFood) -> None:
        self.food = food
        self.words = _words(food.name)
        # Les marques utiles sont parfois plus courtes que le seuil de
        # discrimination : « jus » et « cru » font trois lettres. Elles ne
        # servent pas à retrouver un aliment, mais à le juger — donc une
        # deuxième liste, non filtrée. Sans elle, la pénalité de forme dérivée
        # ne voyait jamais « Tomate, jus, conserve », et le jus sortait devant
        # la tomate en conserve.
        self.all_words = _all_words(food.name)
        self.segment_words = tuple(
            _words(segment) for segment in food.name.split(",")
        )
        # Le FCÉN met systématiquement le mot qui discrimine entre parenthèses,
        # où qu'il tombe dans le nom : « Confiseries, sucre, brun (cassonade) »,
        # « Pâtes (spaghetti, macaroni), enrichi, sec », « Tomates, ketchup
        # (catsup) », « Courge d'été, courgette (zucchini), crue ». Une
        # parenthèse est un synonyme de l'aliment, pas un ingrédient de plus :
        # elle appartient donc à la zone de tête. Sans ça, la cassonade et les
        # pâtes sèches génériques étaient rejetées comme plats composés.
        self.head_zone = tuple(
            word
            for segment in self.segment_words[:_HEAD_SEGMENT_LIMIT]
            for word in segment
        ) + _parenthesised_words(food.name)


def _propose(
    target: MatchTarget,
    by_prefix: Mapping[str, Mapping[str, Sequence[_IndexedFood]]],
    *,
    limit: int,
    rejected_limit: int,
) -> MatchProposal:
    wanted = _words(target.name)
    wanted_markers = _all_words(target.name)
    family_words = tuple(
        word
        for word in _words(target.family_name or "")
        if word not in _GENERIC_FAMILY_WORDS
    )
    retrieved: dict[str, _IndexedFood] = {}
    for word in wanted:
        # « Poireau » doit retrouver « Poireaux » : la recherche se fait au
        # radical, dans le seul seau qui peut contenir une réponse.
        for indexed_word, foods in by_prefix.get(word[:_MIN_WORD], {}).items():
            if _same_stem(word, indexed_word):
                for food in foods:
                    retrieved.setdefault(food.food.food_code, food)

    candidates: list[MatchCandidate] = []
    rejected: list[MatchRejection] = []
    for food in retrieved.values():
        reason = _rejection(food, wanted, wanted_markers)
        if reason is not None:
            rejected.append(
                MatchRejection(food.food.food_code, food.food.name, reason)
            )
            continue
        candidates.append(_scored(food, wanted, wanted_markers, family_words))

    candidates.sort(key=lambda row: (-row.score, int(row.food_code)))
    rejected.sort(key=lambda row: int(row.food_code))
    return MatchProposal(
        ingredient_id=target.ingredient_id,
        ingredient_name=target.name,
        family_name=target.family_name,
        base_unit=target.base_unit,
        blocked_recipes=target.blocked_recipes,
        attached_food_codes=target.attached_food_codes,
        candidates=tuple(candidates[:limit]),
        rejected=tuple(rejected[:rejected_limit]),
    )


def _rejection(
    food: _IndexedFood, wanted: Sequence[str], wanted_markers: Sequence[str]
) -> str | None:
    if _carries(food.all_words, _COOKED_MARKERS) and not _carries(
        wanted_markers, _COOKED_MARKERS
    ):
        return COOKED_OR_PREPARED_FORM
    if not any(
        _same_stem(word, published)
        for published in food.head_zone
        for word in wanted
    ):
        return COMPOSITE_DISH
    return None


def _scored(
    food: _IndexedFood,
    wanted: Sequence[str],
    wanted_markers: Sequence[str],
    family_words: Sequence[str],
) -> MatchCandidate:
    matched = [
        word
        for word in wanted
        if any(_same_stem(word, published) for published in food.words)
    ]
    extras = [
        published
        for published in food.words
        if not any(_same_stem(word, published) for word in wanted)
    ]
    coverage = (
        Decimal(len(matched)) / Decimal(len(wanted)) if wanted else Decimal("0")
    )
    score = coverage * _COVERAGE_WEIGHT
    signals: list[str] = []

    if family_words and any(
        _same_stem(word, published)
        for word in family_words
        for published in food.words
    ):
        score += _FAMILY_BONUS
        signals.append("family_match")
    if _carries(food.all_words, _RAW_MARKERS):
        score += _RAW_BONUS
        signals.append("raw_form")
    # Le FCÉN nomme souvent la classe avant l'aliment — « Grains céréaliers,
    # riz blanc, grain long », « Tomates, ketchup », « Confiseries, sirop
    # d'érable ». Le mot de tête cherché est donc le premier mot du premier
    # **ou** du deuxième segment. Ne regarder que le tout premier mot faisait
    # gagner « Riz espagnol » contre le riz blanc à grain long, et comparer le
    # segment entier faisait gagner « Veau de lait » contre le lait.
    heads = tuple(
        segment[0]
        for segment in food.segment_words[:_HEAD_SEGMENT_LIMIT]
        if segment
    ) + _parenthesised_words(food.food.name)
    if wanted and any(_same_stem(wanted[0], head) for head in heads):
        score += _HEAD_MATCH_BONUS
        signals.append("head_match")
    # Chaque transformation se juge séparément. Prise en bloc, la règle se
    # désarmait d'elle-même : « Biscuit, beurre, Petit Beurre, fait avec de
    # l'huile » porte « beurre », que le canon nomme, et le biscuit passait
    # gratuitement — premier candidat pour du beurre, à 447 kcal/100 g.
    unnamed = [
        word
        for word in _DERIVED_FORMS
        if _carries(food.all_words, (word,))
        and not _carries(wanted_markers, (word,))
    ]
    if unnamed:
        score -= _DERIVED_FORM_PENALTY
        signals.append(f"derived_form:{unnamed[0]}")
    first_segment_extras = [
        published
        for published in (food.segment_words[0] if food.segment_words else ())
        if not any(_same_stem(word, published) for word in wanted)
    ]
    score -= _EXTRA_FIRST_SEGMENT_PENALTY * Decimal(len(first_segment_extras))
    score -= _EXTRA_WORD_PENALTY * Decimal(len(extras))

    return MatchCandidate(
        food_code=food.food.food_code,
        food_name=food.food.name,
        group=food.food.group,
        kcal_per_100g=food.food.kcal_per_100g,
        score=score,
        signals=tuple(signals),
    )


#: Terminaisons qui font d'une marque sa forme fléchie. Comparer par préfixe
#: nu lisait « Poulet à griller » — une catégorie d'oiseau — comme du poulet
#: grillé, et rejetait les seules cuisses de poulet crues du fichier; « cuisse »
#: se lisait comme « cuit » par le même mécanisme.
_MARKER_ENDINGS = ("", "e", "s", "es", "ee", "ees")


def _parenthesised_words(name: str) -> tuple[str, ...]:
    return tuple(
        word
        for group in _PARENTHESES.findall(name)
        for word in _words(group)
    )


def _carries(words: Sequence[str], markers: Sequence[str]) -> bool:
    return any(
        word == marker + ending
        for word in words
        for marker in markers
        for ending in _MARKER_ENDINGS
    )


#: Suffixes qui font d'un mot la forme fléchie d'un autre. La liste est courte
#: exprès : une troncature libre faisait répondre « lait » à « laitue » et
#: « sauce » à « saucisse », ce qui remplit un manifeste de bruit.
_INFLECTIONS = ("s", "x", "e", "es", "ee", "ees")


def _same_stem(left: str, right: str) -> bool:
    """Égalité tolérante au pluriel : « poireau » répond à « poireaux »."""
    if left == right:
        return True
    short, long = sorted((left, right), key=len)
    return long[: len(short)] == short and long[len(short) :] in _INFLECTIONS


def _all_words(text: str) -> tuple[str, ...]:
    """Tous les mots du nom, sans filtre — pour juger, pas pour retrouver."""
    return tuple(_split(text))


def _words(text: str) -> tuple[str, ...]:
    """Mots significatifs — ceux qui peuvent retrouver un aliment.

    Les nombres comptent, et c'est ce qui manquait : sans eux, « Crème 35 % »
    ne pouvait pas préférer « Crème à fouetter, 35 % M.G. » (328 kcal, 35 g de
    lipides) à « Crème, légère, 5 % M.G. » (72 kcal, 5 g), et le classement
    retombait sur la brièveté du libellé. Même cause pour « Lait 3,25 % »,
    qui ressortait sur du lait écrémé. Un taux de matière grasse n'est pas un
    ornement du nom : c'est ce qui distingue deux aliments d'un facteur quatre.
    """
    return tuple(
        word
        for word in _split(text)
        if word.isdigit() or (len(word) >= _MIN_WORD and word not in _STOP_WORDS)
    )


#: Ligatures que la décomposition Unicode ne défait pas. « Œuf » restait
#: « œuf » et ne répondait donc jamais à « Oeuf » du fichier fédéral.
_LIGATURES = {"œ": "oe", "Œ": "oe", "æ": "ae", "Æ": "ae", "ﬁ": "fi"}


def _split(text: str) -> list[str]:
    for ligature, plain in _LIGATURES.items():
        text = text.replace(ligature, plain)
    folded = "".join(
        character
        for character in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(character) != "Mn"
    )
    return "".join(
        character if character.isalnum() else " " for character in folded
    ).split()
