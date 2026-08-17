"""Règles d'approvisionnement et leur résolution, en un seul endroit.

Une règle dit comment obtenir un ingrédient qu'aucun produit ne vend tel quel :
soit il est fourni sans achat d'épicerie (``essential``, l'eau du robinet), soit
il s'obtient d'un autre ingrédient dans un rapport connu (``derived``, le jus de
citron depuis le citron).

Deux modules lisent le même fichier de règles — le calcul de prix et l'audit de
couverture. Ils en tiraient deux réponses différentes : le premier ne suivait
qu'un seul saut et exigeait un produit commercial au bout, le second itérait
jusqu'au point fixe. L'audit annonçait donc une couverture que le calcul ne
savait pas livrer. La résolution vit ici, et eux ne font plus que l'appeler.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

_CONFIDENCE_RANK = {
    "exact": 0,
    "audited_conversion": 1,
    "estimated": 2,
    "incomplete": 3,
}

#: Garde-fou de dernier recours : une chaîne plus longue que ça n'est pas une
#: conversion, c'est une erreur de curation.
_MAX_CHAIN = 16


class CyclicSupplyRuleError(ValueError):
    """Les règles se renvoient l'une à l'autre; aucune ne peut se résoudre."""


@dataclass(frozen=True)
class SupplyRule:
    ingredient_id: str
    kind: str
    source_ingredient_id: str | None = None
    source_qty_per_target_unit: Decimal | None = None
    confidence: str = "audited_conversion"
    provenance: str = ""


@dataclass(frozen=True)
class Resolution:
    """Ce qu'il faut acheter pour couvrir un ingrédient, et à quel titre.

    ``kind`` vaut ``direct`` (l'ingrédient s'achète tel quel), ``derived`` (il
    s'obtient d'un autre, ``factor`` fois sa quantité), ``essential`` (aucun
    achat d'épicerie) ou ``invalid_rule`` (la règle est incomplète et le dit).
    """

    kind: str
    procurement_ingredient_id: str | None
    factor: Decimal
    confidence: str
    provenance: str | None
    chain: tuple[str, ...]


def parse_supply_rules(payload: Mapping) -> tuple[SupplyRule, ...]:
    """Lit le bloc ``supply_rules`` du fichier de règles d'approvisionnement.

    Trois appelants le lisaient chacun de leur côté — la façade SQL, le script
    de devis et le script d'audit — et le troisième oubliait
    ``source_qty_per_target_unit``. Ses règles dérivées étaient donc toutes
    incomplètes, ce qui suffisait à faire diverger l'audit du calcul de prix
    même une fois la résolution partagée.
    """
    return tuple(
        SupplyRule(
            ingredient_id=str(row["ingredient_id"]),
            kind=str(row["kind"]),
            source_ingredient_id=row.get("source_ingredient_id"),
            source_qty_per_target_unit=(
                Decimal(str(row["source_qty_per_target_unit"]))
                if row.get("source_qty_per_target_unit") is not None
                else None
            ),
            confidence=str(row.get("confidence", "audited_conversion")),
            provenance=str(row.get("provenance", "")),
        )
        for row in payload.get("supply_rules", [])
    )


def resolve_supply(
    ingredient_id: str, rules: Mapping[str, SupplyRule]
) -> Resolution:
    """Suit la chaîne de règles jusqu'à un ingrédient réellement achetable."""
    factor = Decimal("1")
    confidence = "exact"
    provenance: str | None = None
    chain = [ingredient_id]
    current = ingredient_id
    seen = {ingredient_id}

    for _ in range(_MAX_CHAIN):
        rule = rules.get(current)
        if rule is None:
            return Resolution(
                "direct" if len(chain) == 1 else "derived",
                current,
                factor,
                confidence,
                provenance,
                tuple(chain),
            )
        if rule.kind == "essential":
            return Resolution(
                "essential",
                None,
                factor,
                _worst_confidence(confidence, rule.confidence),
                rule.provenance or provenance,
                tuple(chain),
            )
        if rule.kind != "derived":
            raise ValueError(
                f"Type de règle d'approvisionnement inconnu: {rule.kind!r} "
                f"pour {rule.ingredient_id!r}."
            )
        if not rule.source_ingredient_id or rule.source_qty_per_target_unit is None:
            return Resolution(
                "invalid_rule",
                None,
                factor,
                "incomplete",
                rule.provenance or provenance,
                tuple(chain),
            )
        factor *= Decimal(str(rule.source_qty_per_target_unit))
        confidence = _worst_confidence(confidence, rule.confidence)
        # La provenance de la première conversion est celle que la ligne
        # d'ingrédient affiche; les suivantes s'y ajoutent.
        provenance = (
            rule.provenance
            if provenance is None
            else f"{provenance} — {rule.provenance}"
            if rule.provenance
            else provenance
        )
        current = rule.source_ingredient_id
        if current in seen:
            raise CyclicSupplyRuleError(
                "Chaîne de règles d'approvisionnement cyclique: "
                + " → ".join(chain + [current])
            )
        seen.add(current)
        chain.append(current)

    raise CyclicSupplyRuleError(
        "Chaîne de règles d'approvisionnement trop longue: " + " → ".join(chain)
    )


def _worst_confidence(*values: str) -> str:
    unknown = [value for value in values if value not in _CONFIDENCE_RANK]
    if unknown:
        raise ValueError(f"Niveau de confiance inconnu: {unknown[0]!r}")
    return max(values, key=_CONFIDENCE_RANK.__getitem__)
