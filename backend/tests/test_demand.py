"""Encadrement de la demande (D9) — dont le cas explicite du D non entier."""

from decimal import Decimal

import pytest

from app.services.demand import compute_demand_bounds


def test_non_integer_D_from_seed_profile():
    """LE cas de test demandé au point de contrôle : deux adultes + un enfant
    (ρ = 1,0 / 1,0 / 0,6) sur 14 repas → D = 36,4, non entier. L'égalité
    stricte Σx_r = D serait infaisable en entiers ; l'encadrement donne
    ⌈36,4⌉ = 37 ≤ Σx_r ≤ ⌈36,4·1,1⌉ = ⌈40,04⌉ = 41."""
    b = compute_demand_bounds(
        14, [Decimal("1.0"), Decimal("1.0"), Decimal("0.6")], Decimal("0.10")
    )
    assert b.exact == Decimal("36.4")
    assert b.low == 37
    assert b.high == 41
    assert b.low <= b.high


def test_integer_D_low_equals_exact():
    b = compute_demand_bounds(4, [Decimal("1.0")], Decimal("0.10"))
    assert b.exact == Decimal("4") and b.low == 4 and b.high == 5


def test_epsilon_zero_pins_both_bounds_to_ceiling():
    b = compute_demand_bounds(
        14, [Decimal("1.0"), Decimal("1.0"), Decimal("0.6")], Decimal("0")
    )
    assert b.low == b.high == 37


def test_invalid_inputs():
    with pytest.raises(ValueError):
        compute_demand_bounds(0, [Decimal("1")], Decimal("0.1"))
    with pytest.raises(ValueError):
        compute_demand_bounds(4, [Decimal("1")], Decimal("-0.1"))
