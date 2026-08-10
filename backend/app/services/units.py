"""Conversion d'unités — LA fonction unique du projet (docs/spec.md,
« Exigences transverses »).

Toute conversion masse↔volume exige une densité non nulle ; **jamais** de
défaut à 1,0 : l'absence de densité lève une exception explicite.
"""

from __future__ import annotations

from decimal import Decimal

#: Unités de base par famille — seule vérité sur la correspondance
#: unit_kind ↔ base_unit (utilisée par l'assertion 3).
BASE_UNIT_OF_KIND = {"mass": "g", "volume": "ml", "count": "unit"}


class MissingDensityError(ValueError):
    """Conversion masse↔volume demandée sans ``density_g_per_ml``."""


class IncompatibleUnitsError(ValueError):
    """Conversion impossible entre ces familles d'unités."""


def convert_qty(
    qty: Decimal,
    from_unit: str,
    to_unit: str,
    density_g_per_ml: Decimal | None = None,
) -> Decimal:
    """Convertit ``qty`` de ``from_unit`` vers ``to_unit``.

    Unités reconnues : ``g`` (masse), ``ml`` (volume), ``unit`` (compte).
    - identité si les unités sont égales ;
    - g↔ml via ``density_g_per_ml`` (exception explicite si absente ou nulle) ;
    - toute conversion impliquant ``unit`` est refusée : un œuf ne se convertit
      pas en grammes sans référentiel produit, hors périmètre v1.
    """
    if from_unit == to_unit:
        return qty
    pair = {from_unit, to_unit}
    if pair == {"g", "ml"}:
        if not density_g_per_ml:  # None ou 0 — jamais 1,0 par défaut
            raise MissingDensityError(
                f"Conversion {from_unit}→{to_unit} impossible : "
                "density_g_per_ml absente ou nulle (aucun défaut appliqué)."
            )
        if from_unit == "ml":
            return qty * density_g_per_ml
        return qty / density_g_per_ml
    raise IncompatibleUnitsError(
        f"Conversion {from_unit}→{to_unit} non prise en charge."
    )
