"""Règles nutritionnelles déclarées : apports négligeables et aliment retenu.

Deux règlements, un seul fichier versionné (``config/nutrition-rules.json``),
parce que les deux répondent à la même question — « que fait-on d'un ingrédient
dont le FCÉN ne dit pas ce qu'il faudrait » — et qu'ils doivent être lus par
les mêmes trois appelants : le module de calcul, la façade HTTP et l'audit de
couverture.

**Apport négligeable.** Un ingrédient déclaré négligeable ne contribue pas au
total, et la règle dit de combien elle se trompe en l'omettant. La borne n'est
jamais saisie à la main : l'entrée déclare la teneur fédérale mesurée
(``kcal_per_100g``, avec le code d'aliment en provenance), le plafond de
quantité sur lequel la déclaration porte, et le plafond de masse par unité de
base. La borne s'en déduit. Une entrée sans teneur mesurée est refusée — sans
elle, « négligeable » est une omission qui s'ignore, pas une règle.

**Le plafond de quantité n'est pas décoratif.** Une déclaration porte sur un
assaisonnement, pas sur un aliment : le même basilic frais qui pèse 1 g dans un
plat en pèse 187 g par portion dans une panzanella de ce corpus (375 g pour
deux portions, à côté de 2 000 g de roquette — une conversion millilitre→gramme
fautive à l'import). Au-delà du plafond, la déclaration se retire et
l'ingrédient redevient bloquant : la donnée fautive remonte au lieu d'être
absorbée en silence par une borne de 0 kcal.

**Aliment retenu.** Le pont canonique → FCÉN a été curé pour l'identité
commerciale, pas pour la nutrition : 26 ingrédients portent plusieurs aliments
FCÉN (l'avocat en porte trois, de 120 à 167 kcal/100 g — l'écart n'est pas
arbitrable par un tri), et certains en portent un qui nomme une autre classe
d'aliment (``mais`` a été créé depuis « Pâtes, maïs, sèches », 357 kcal/100 g
au lieu de 86). Le module ne choisit donc jamais tout seul : il lit un choix
déclaré, motivé par écrit, ou il refuse en nommant l'ambiguïté.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Mapping, Sequence

__all__ = [
    "BASE_UNIT_MISMATCH",
    "CHOICE_KINDS",
    "FoodChoice",
    "NEGLIGIBLE",
    "NOT_DECLARED",
    "NegligibleBounds",
    "NegligibleClaim",
    "NegligibleVerdict",
    "NutritionRuleset",
    "NutritionRulesInvalid",
    "OVER_DECLARED_QUANTITY",
    "parse_nutrition_rules",
    "parse_verified_unit_masses",
]

#: Verdicts possibles d'une demande d'apport négligeable.
NEGLIGIBLE = "negligible"
NOT_DECLARED = "not_declared"
OVER_DECLARED_QUANTITY = "over_declared_quantity"
BASE_UNIT_MISMATCH = "base_unit_mismatch"

#: Titres sous lesquels un aliment FCÉN peut être retenu pour un ingrédient.
#: ``primary`` : l'ingrédient porte plusieurs aliments, celui-ci est le bon.
#: ``correction`` : les aliments portés nomment une autre classe d'aliment.
#: ``substitution`` : le FCÉN ne publie pas cette variété, un générique
#: nutritionnellement équivalent la remplace (basmati, dijon).
#: ``attachment`` : la curation d'identité n'a rien rattaché à cet ingrédient,
#: et le FCÉN publie bien l'aliment. Le pont canonique → FCÉN a été curé pour
#: l'identité commerciale, sous des contrôles qu'un aliment parfaitement
#: nutritif peut échouer; le règlement retient l'aliment sans réécrire ce pont.
#: Refusé si l'ingrédient porte déjà un aliment : c'est alors « primary » ou
#: « correction », qui disent pourquoi le rattachement existant ne convient pas.
CHOICE_KINDS = ("primary", "correction", "substitution", "attachment")

#: Précision des bornes affichées. Une borne s'arrondit **vers le haut** :
#: arrondie vers le bas, elle cesse d'être une borne.
_TENTH = Decimal("0.1")

_KNOWN_BASE_UNITS = ("g", "ml", "unit")


class NutritionRulesInvalid(ValueError):
    """Le fichier de règles nutritionnelles est incomplet ou incohérent.

    Nommée, parce qu'une règle à moitié écrite est plus dangereuse qu'une règle
    absente : elle produit un total plausible. Le refus cite le champ manquant.
    """


@dataclass(frozen=True)
class NegligibleBounds:
    """Ce qu'une omission coûte, sur les quatre nombres publiés."""

    kcal: Decimal
    protein_g: Decimal
    fat_g: Decimal
    carbohydrate_g: Decimal


@dataclass(frozen=True)
class NegligibleClaim:
    """Déclaration bornée d'un apport nul, et ce qu'elle a coûté à mesurer.

    Les quatre teneurs sont exigées, pas seulement l'énergie. Une déclaration
    qui ne bornait que les calories laissait publier les macros comme exactes :
    à 2,5 g d'une épice quelconque, jusqu'à 1,04 g de lipides disparaissaient
    en silence pendant que les 13,2 kcal, elles, s'affichaient. Un gramme de
    gras non déclaré n'est pas plus acceptable qu'une calorie non déclarée.
    """

    scope: str
    scope_id: str
    base_unit: str
    kcal_per_100g: Decimal
    protein_g_per_100g: Decimal
    fat_g_per_100g: Decimal
    carbohydrate_g_per_100g: Decimal
    max_qty_per_serving: Decimal
    grams_per_base_unit_ceiling: Decimal
    basis: str
    provenance: str

    def bounds_at(self, qty_per_serving: Decimal) -> NegligibleBounds:
        """Apport maximal omis pour cette quantité, arrondi vers le haut."""
        grams = qty_per_serving * self.grams_per_base_unit_ceiling
        return NegligibleBounds(
            kcal=_ceil_tenth(self.kcal_per_100g * grams / 100),
            protein_g=_ceil_tenth(self.protein_g_per_100g * grams / 100),
            fat_g=_ceil_tenth(self.fat_g_per_100g * grams / 100),
            carbohydrate_g=_ceil_tenth(
                self.carbohydrate_g_per_100g * grams / 100
            ),
        )

    def kcal_bound_at(self, qty_per_serving: Decimal) -> Decimal:
        return self.bounds_at(qty_per_serving).kcal

    @property
    def kcal_bound_at_ceiling(self) -> Decimal:
        """Le pire que la déclaration admette — ce qu'elle promet vraiment."""
        return self.kcal_bound_at(self.max_qty_per_serving)

    @property
    def bounds_at_ceiling(self) -> NegligibleBounds:
        return self.bounds_at(self.max_qty_per_serving)


@dataclass(frozen=True)
class NegligibleVerdict:
    kind: str
    kcal_bound: Decimal
    claim: NegligibleClaim | None = None
    reason: str | None = None
    bounds: NegligibleBounds = NegligibleBounds(
        Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
    )


@dataclass(frozen=True)
class FoodChoice:
    ingredient_id: str
    food_code: str
    kind: str
    rationale: str
    provenance: str


@dataclass(frozen=True)
class NutritionRuleset:
    rule_version: str
    negligible: tuple[NegligibleClaim, ...]
    food_choices: tuple[FoodChoice, ...]
    #: Édition de l'archive fédérale sur laquelle les bornes ont été mesurées.
    #: Les appliquer aux teneurs d'une autre édition invaliderait la mesure :
    #: le lecteur SQL s'y restreint donc explicitement.
    source_version: str = "2026"

    def __post_init__(self) -> None:
        # Index construits une fois : la résolution est appelée une fois par
        # ligne d'ingrédient de chaque recette, et un balayage des règles à
        # chaque appel se paierait sur 161 recettes pour rien.
        object.__setattr__(
            self,
            "_by_ingredient",
            {c.scope_id: c for c in self.negligible if c.scope == "ingredient"},
        )
        object.__setattr__(
            self,
            "_by_family",
            {c.scope_id: c for c in self.negligible if c.scope == "family"},
        )
        object.__setattr__(
            self, "_choices", {c.ingredient_id: c for c in self.food_choices}
        )

    def negligible_verdict(
        self,
        *,
        ingredient_id: str,
        family_id: str | None,
        base_unit: str,
        qty_per_serving: Decimal,
    ) -> NegligibleVerdict:
        """Dit si l'omission de cet ingrédient est déclarée, et à quel prix."""
        claim = self._claim_for(ingredient_id, family_id)
        if claim is None:
            return NegligibleVerdict(NOT_DECLARED, Decimal("0"))
        if claim.base_unit != base_unit:
            return NegligibleVerdict(
                BASE_UNIT_MISMATCH,
                Decimal("0"),
                claim,
                f"La borne de {claim.scope_id!r} est mesurée par "
                f"{claim.base_unit}; {ingredient_id!r} se compte en "
                f"{base_unit}.",
            )
        if qty_per_serving > claim.max_qty_per_serving:
            return NegligibleVerdict(
                OVER_DECLARED_QUANTITY,
                Decimal("0"),
                claim,
                f"{qty_per_serving} {base_unit} par portion dépassent le "
                f"plafond déclaré de {claim.max_qty_per_serving} "
                f"{claim.base_unit} : au-delà, l'apport n'a pas été mesuré "
                f"négligeable (borne au plafond : "
                f"{claim.kcal_bound_at_ceiling} kcal).",
            )
        bounds = claim.bounds_at(qty_per_serving)
        return NegligibleVerdict(NEGLIGIBLE, bounds.kcal, claim, None, bounds)

    def food_choice(self, ingredient_id: str) -> FoodChoice | None:
        choices: Mapping[str, FoodChoice] = getattr(self, "_choices")
        return choices.get(ingredient_id)

    def _claim_for(
        self, ingredient_id: str, family_id: str | None
    ) -> NegligibleClaim | None:
        """L'entrée par ingrédient l'emporte sur celle de sa famille.

        Le sel est une épice au sens du canon, mais sa borne (0 kcal, jusqu'à
        15 g) est plus large et plus sûre que celle de sa famille (2,5 g d'une
        épice moulue quelconque). Sans précédence, la déclaration la plus
        précise serait la plus restrictive.
        """
        by_ingredient: Mapping[str, NegligibleClaim] = getattr(
            self, "_by_ingredient"
        )
        if ingredient_id in by_ingredient:
            return by_ingredient[ingredient_id]
        if family_id is None:
            return None
        by_family: Mapping[str, NegligibleClaim] = getattr(self, "_by_family")
        return by_family.get(family_id)


def parse_nutrition_rules(payload: Mapping) -> NutritionRuleset:
    """Lit le fichier de règles nutritionnelles, ou refuse en nommant le trou."""
    version = str(payload.get("rule_version") or "").strip()
    if not version:
        raise NutritionRulesInvalid(
            "rule_version manquante : un règlement non versionné ne peut pas "
            "être cité par un chiffre publié."
        )
    claims = tuple(
        _claim(row, index)
        for index, row in enumerate(
            _entries(payload, "negligible_contributions")
        )
    )
    _refuse_duplicates(claims)
    choices = tuple(
        _choice(row, index)
        for index, row in enumerate(_entries(payload, "food_choices"))
    )
    source_version = str(payload.get("source_version") or "").strip()
    if not source_version:
        raise NutritionRulesInvalid(
            "source_version manquante : une borne mesurée sur une édition de "
            "l'archive ne vaut pas pour une autre."
        )
    seen: set[str] = set()
    for choice in choices:
        if choice.ingredient_id in seen:
            raise NutritionRulesInvalid(
                f"L'ingrédient {choice.ingredient_id!r} retient deux aliments "
                "FCÉN : le choix ne serait pas un choix."
            )
        seen.add(choice.ingredient_id)
    return NutritionRuleset(version, claims, choices, source_version)


def _entries(payload: Mapping, key: str) -> Sequence[Mapping]:
    """Le bloc nommé, ou un refus nommé — jamais un TypeError.

    `payload.get(key, [])` ne défend que de la clé absente. Une clé à `null` ou
    une entrée qui n'est pas un objet remontait en `TypeError`/`AttributeError`
    depuis le fond de la couche services, et la façade ne rattrape que
    `NutritionRulesInvalid` : un fichier à moitié écrit devenait une 500 au lieu
    d'une 503 qui nomme le fichier.
    """
    block = payload.get(key, [])
    # Une clé à `null` est refusée, pas assimilée à une clé absente : elle dit
    # qu'on a commencé à écrire ce bloc.
    if not isinstance(block, Sequence) or isinstance(block, (str, bytes)):
        raise NutritionRulesInvalid(
            f"{key} n'est pas une liste d'entrées ({type(block).__name__})."
        )
    for index, row in enumerate(block):
        if not isinstance(row, Mapping):
            raise NutritionRulesInvalid(
                f"{key}[{index}] n'est pas une entrée ({type(row).__name__})."
            )
    return block


def _claim(row: Mapping, index: int) -> NegligibleClaim:
    where = f"negligible_contributions[{index}]"
    ingredient_id = _optional_text(row.get("ingredient_id"))
    family_id = _optional_text(row.get("family_id"))
    if bool(ingredient_id) == bool(family_id):
        raise NutritionRulesInvalid(
            f"{where} doit nommer exactement une portée : ingredient_id ou "
            "family_id. Une entrée qui nomme les deux (ou aucune) ne dit pas "
            "sur quoi elle porte."
        )
    base_unit = _required_text(row, "base_unit", where)
    if base_unit not in _KNOWN_BASE_UNITS:
        raise NutritionRulesInvalid(
            f"{where}: base_unit {base_unit!r} inconnue "
            f"(attendu : {', '.join(_KNOWN_BASE_UNITS)})."
        )
    kcal = _required_decimal(row, "kcal_per_100g", where, minimum=Decimal("0"))
    protein = _required_decimal(
        row, "protein_g_per_100g", where, minimum=Decimal("0")
    )
    fat = _required_decimal(row, "fat_g_per_100g", where, minimum=Decimal("0"))
    carbohydrate = _required_decimal(
        row, "carbohydrate_g_per_100g", where, minimum=Decimal("0")
    )
    max_qty = _required_decimal(
        row, "max_qty_per_serving_base_unit", where, strictly_positive=True
    )
    ceiling = _required_decimal(
        row, "grams_per_base_unit_ceiling", where, strictly_positive=True
    )
    if base_unit == "g" and ceiling != Decimal("1"):
        raise NutritionRulesInvalid(
            f"{where}: grams_per_base_unit_ceiling vaut {ceiling} pour une "
            "borne mesurée par gramme. Un gramme est un gramme; toute autre "
            "valeur est une faute de saisie."
        )
    return NegligibleClaim(
        scope="ingredient" if ingredient_id else "family",
        scope_id=ingredient_id or family_id or "",
        base_unit=base_unit,
        kcal_per_100g=kcal,
        protein_g_per_100g=protein,
        fat_g_per_100g=fat,
        carbohydrate_g_per_100g=carbohydrate,
        max_qty_per_serving=max_qty,
        grams_per_base_unit_ceiling=ceiling,
        basis=_required_text(row, "basis", where),
        provenance=_required_text(row, "provenance", where),
    )


def _choice(row: Mapping, index: int) -> FoodChoice:
    where = f"food_choices[{index}]"
    kind = _required_text(row, "kind", where)
    if kind not in CHOICE_KINDS:
        raise NutritionRulesInvalid(
            f"{where}: kind {kind!r} inconnu (attendu : "
            f"{', '.join(CHOICE_KINDS)})."
        )
    return FoodChoice(
        ingredient_id=_required_text(row, "ingredient_id", where),
        food_code=_required_text(row, "food_code", where),
        kind=kind,
        rationale=_required_text(row, "rationale", where),
        provenance=_required_text(row, "provenance", where),
    )


def _refuse_duplicates(claims: Sequence[NegligibleClaim]) -> None:
    seen: set[tuple[str, str]] = set()
    for claim in claims:
        key = (claim.scope, claim.scope_id)
        if key in seen:
            raise NutritionRulesInvalid(
                f"L'apport de {claim.scope_id!r} est déclaré deux fois : "
                "deux bornes pour un même fait finissent par diverger."
            )
        seen.add(key)


def _optional_text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _required_text(row: Mapping, field: str, where: str) -> str:
    value = _optional_text(row.get(field))
    if not value:
        raise NutritionRulesInvalid(
            f"{where}: {field} manquant. Une règle sans ce champ n'est pas "
            "vérifiable par son lecteur."
        )
    return value


def _required_decimal(
    row: Mapping,
    field: str,
    where: str,
    *,
    minimum: Decimal | None = None,
    strictly_positive: bool = False,
) -> Decimal:
    raw = row.get(field)
    if raw is None or _optional_text(raw) == "":
        raise NutritionRulesInvalid(
            f"{where}: {field} manquant. Sans lui la borne n'a jamais été "
            "mesurée, et « négligeable » ne serait qu'une omission."
        )
    try:
        value = Decimal(str(raw))
    except InvalidOperation as error:
        raise NutritionRulesInvalid(
            f"{where}: {field} illisible ({raw!r})."
        ) from error
    if strictly_positive and value <= 0:
        raise NutritionRulesInvalid(
            f"{where}: {field} doit être strictement positif (reçu {value})."
        )
    if minimum is not None and value < minimum:
        raise NutritionRulesInvalid(
            f"{where}: {field} doit valoir au moins {minimum} (reçu {value})."
        )
    return value


def _ceil_tenth(value: Decimal) -> Decimal:
    return value.quantize(_TENTH, rounding=ROUND_CEILING)


def parse_verified_unit_masses(payload: Mapping) -> dict[str, Decimal]:
    """Masses par unité **vérifiées** de ``config/cook_recipe_curation.json``.

    La convention existe déjà pour l'import des recettes : les clés y sont
    ``<ingredient>|<mot d'unité de la recette>`` (``piment_jalapeno|unit``,
    ``celeri|stalk``) et la provenance vit dans ``grams_per_unit_provenance``.
    Seules les clés en ``|unit`` correspondent à l'unité de base ``unit`` du
    canon, et seules les masses *vérifiées* sont retenues : une estimation
    suffit à convertir une quantité d'achat, pas à publier une valeur nutritive.

    Deux appelants la lisent — la façade SQL et le script d'audit. La règle de
    clé vit donc ici, pas en deux copies.
    """
    masses: dict[str, Decimal] = {}
    for key, grams in payload.get("verified_grams_per_unit", {}).items():
        ingredient_id, _, unit_word = str(key).partition("|")
        if unit_word != "unit" or not ingredient_id:
            continue
        try:
            mass = Decimal(str(grams))
        except InvalidOperation as error:
            # Une faute de frappe en curation remontait en `InvalidOperation`
            # depuis le fond de la couche services, donc en 500 sur la route.
            raise NutritionRulesInvalid(
                f"verified_grams_per_unit[{key!r}] illisible ({grams!r})."
            ) from error
        if mass <= 0:
            # `0` n'est pas « masse inconnue » : c'est une masse fausse. Lue
            # comme absente, elle rendait l'ingrédient bloquant pour la mauvaise
            # raison, et le curateur aurait cherché une donnée déjà saisie.
            raise NutritionRulesInvalid(
                f"verified_grams_per_unit[{key!r}] vaut {mass} : une masse par "
                "unité est strictement positive. Retirer la clé si la masse "
                "est inconnue."
            )
        masses[ingredient_id] = mass
    return masses
