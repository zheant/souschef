"""Coûts de déplacement — formules imposées (docs/spec.md, « Paramètres
calculés »). Fonction unique, documentée, testée.

    f^sortie = 4,00 $        f^marg_s = 1,50 $ + 0,60 · 2·d_s

où d_s est la distance à vol d'oiseau domicile→magasin en km **majorée de
30 %** pour approximer le trajet routier, donc en cents :

    f^marg_s = 150 + 60 · 2 · (1,3·d_vol) = 150 + 156·d_vol.

Centre commercial partagé : si un magasin partage un ``shopping_center_id``
avec un magasin déjà visité, son terme forfaitaire de 1,50 $ tombe à 0,25 $ et
la distance n'est pas recomptée. Pour rester linéaire dans le MILP, le coût
est décomposé par centre (un magasin sans centre est son propre centre) :

    coût = Σ_centres v_c·(125 + 156·d_c) + Σ_magasins 25·z_s

avec v_c = 1 ssi au moins un magasin du centre est visité, et d_c la distance
au centre (min des d_s des magasins du centre — quasi identiques par
définition). Pour un centre à magasin unique, la somme redonne exactement
150 + 156·d_s ; pour deux magasins visités du même centre :
(125 + 156·d) + 25 + 25 = 175 + 156·d = (150 + 156·d) + 25, soit le premier au
tarif plein et le second à 0,25 $, distance non recomptée. ✓

Ces coûts dépendent du domicile du ménage : paramètres **par utilisateur**,
calculés à la construction du modèle, jamais stockés comme constante globale.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import asin, cos, radians, sin, sqrt

from .problem_data import StoreData

F_SORTIE_CENTS = 400
_STOP_FLAT_CENTS = Decimal("150")
_STOP_SHARED_CENTER_CENTS = Decimal("25")
_CENTS_PER_KM = Decimal("156")  # 60 c/km · 2 (aller-retour) · 1,3 (routier)
_EARTH_RADIUS_KM = Decimal("6371")


def haversine_km(lat1: Decimal, lng1: Decimal, lat2: Decimal, lng2: Decimal) -> Decimal:
    """Distance à vol d'oiseau, en km."""
    a1, o1, a2, o2 = (radians(float(v)) for v in (lat1, lng1, lat2, lng2))
    h = sin((a2 - a1) / 2) ** 2 + cos(a1) * cos(a2) * sin((o2 - o1) / 2) ** 2
    return (Decimal(2) * _EARTH_RADIUS_KM * Decimal(asin(sqrt(h)))).quantize(
        Decimal("0.0001")
    )


def marginal_stop_cost_cents(d_vol_km: Decimal) -> Decimal:
    """f^marg_s complet (magasin isolé ou premier d'un centre) : 150 + 156·d."""
    return (_STOP_FLAT_CENTS + _CENTS_PER_KM * d_vol_km).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class TravelCosts:
    """Décomposition linéarisable des coûts de déplacement pour UN domicile."""

    f_sortie_cents: int
    #: d_s (vol d'oiseau, km) par store id.
    distance_km: dict[int, Decimal]
    #: centre → magasins du centre (magasin isolé = centre singleton "__s<id>").
    center_stores: dict[str, tuple[int, ...]]
    #: coût d'ancrage du centre (125 + 156·d_c), payé si v_c = 1.
    center_anchor_cents: dict[str, Decimal]
    #: coût par arrêt (25), payé pour chaque z_s = 1.
    per_stop_cents: Decimal


def compute_travel_costs(
    home_lat: Decimal, home_lng: Decimal, stores: tuple[StoreData, ...]
) -> TravelCosts:
    distance = {
        s.id: haversine_km(home_lat, home_lng, s.lat, s.lng) for s in stores
    }
    centers: dict[str, list[int]] = {}
    for s in stores:
        key = s.shopping_center_id or f"__solo_{s.id}"
        centers.setdefault(key, []).append(s.id)
    anchor = {
        c: (
            _STOP_FLAT_CENTS
            - _STOP_SHARED_CENTER_CENTS
            + _CENTS_PER_KM * min(distance[sid] for sid in sids)
        ).quantize(Decimal("0.01"))
        for c, sids in centers.items()
    }
    return TravelCosts(
        f_sortie_cents=F_SORTIE_CENTS,
        distance_km=distance,
        center_stores={c: tuple(sorted(sids)) for c, sids in centers.items()},
        center_anchor_cents=anchor,
        per_stop_cents=_STOP_SHARED_CENTER_CENTS,
    )
