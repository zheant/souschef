from decimal import Decimal

from app.services.problem_data import StoreData
from app.services.travel import (
    compute_travel_costs, haversine_km, marginal_stop_cost_cents,
)


def make_store(sid, key, lat, lng, center=None):
    return StoreData(id=sid, external_key=key, banner=key,
                     lat=Decimal(str(lat)), lng=Decimal(str(lng)),
                     shopping_center_id=center)


def test_haversine_known_distance():
    # ~1° de latitude ≈ 111,2 km
    d = haversine_km(Decimal("45.0"), Decimal("-73.6"),
                     Decimal("46.0"), Decimal("-73.6"))
    assert Decimal("111.0") < d < Decimal("111.4")


def test_marginal_stop_formula():
    # f_marg = 150 + 60·2·(1,3·d) = 150 + 156·d
    assert marginal_stop_cost_cents(Decimal("2")) == Decimal("462.00")
    assert marginal_stop_cost_cents(Decimal("0")) == Decimal("150.00")


def test_singleton_center_recomposes_full_formula():
    home = (Decimal("45.5285"), Decimal("-73.5980"))
    s = make_store(1, "solo", 45.5210, -73.5730)
    t = compute_travel_costs(*home, (s,))
    d = t.distance_km[1]
    # ancrage (125 + 156·d) + arrêt (25) = 150 + 156·d = f_marg complet
    total = t.center_anchor_cents["__solo_1"] + t.per_stop_cents
    assert total == marginal_stop_cost_cents(d)


def test_shared_center_second_stop_costs_25_cents():
    home = (Decimal("45.5285"), Decimal("-73.5980"))
    s1 = make_store(1, "a", 45.5602, -73.6512, center="c1")
    s2 = make_store(2, "b", 45.5598, -73.6505, center="c1")
    t = compute_travel_costs(*home, (s1, s2))
    d_min = min(t.distance_km.values())
    both = t.center_anchor_cents["c1"] + 2 * t.per_stop_cents
    first_alone = marginal_stop_cost_cents(d_min)
    # visiter les deux = premier au tarif plein + 0,25 $, distance non recomptée
    assert both == first_alone + Decimal("25")
    assert t.f_sortie_cents == 400
