from decimal import Decimal

import pytest

from app.services.units import (
    IncompatibleUnitsError, MissingDensityError, convert_qty,
)


def test_identity():
    assert convert_qty(Decimal("42"), "g", "g") == Decimal("42")


def test_ml_to_g_uses_density():
    assert convert_qty(Decimal("100"), "ml", "g", Decimal("1.03")) == Decimal("103.00")


def test_g_to_ml_inverse():
    out = convert_qty(Decimal("103"), "g", "ml", Decimal("1.03"))
    assert out.quantize(Decimal("0.01")) == Decimal("100.00")


def test_missing_density_raises_never_defaults_to_one():
    with pytest.raises(MissingDensityError):
        convert_qty(Decimal("100"), "ml", "g", None)
    with pytest.raises(MissingDensityError):
        convert_qty(Decimal("100"), "g", "ml", Decimal("0"))


def test_count_conversions_refused():
    with pytest.raises(IncompatibleUnitsError):
        convert_qty(Decimal("1"), "unit", "g", Decimal("60"))
