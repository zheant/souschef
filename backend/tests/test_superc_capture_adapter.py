"""Rapprochement Super C vers les ingrédients canoniques Souschef."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from app.adapters.maxi_capture import ProductQuantityConversion
from app.adapters.superc_capture import SuperCCaptureAdapter


def _write_seed(tmp_path):
    seed = tmp_path / "seed"
    seed.mkdir(parents=True)
    ingredients = [
        {"id": "farine_tout_usage", "name": "Farine tout usage", "unit_kind": "mass", "base_unit": "g"},
        {"id": "pomme_de_terre", "name": "Pomme de terre", "unit_kind": "mass", "base_unit": "g"},
        {"id": "banane", "name": "Banane", "unit_kind": "mass", "base_unit": "g"},
        {"id": "boeuf_hache", "name": "Bœuf haché mi-maigre", "unit_kind": "mass", "base_unit": "g"},
        {"id": "tomate_conserve", "name": "Tomates en conserve", "unit_kind": "mass", "base_unit": "g"},
        {"id": "tortilla", "name": "Tortilla", "unit_kind": "count", "base_unit": "unit"},
        {"id": "oignon_vert", "name": "Oignon vert", "unit_kind": "mass", "base_unit": "g"},
    ]
    aliases = [
        {"canonical_ingredient_id": "farine_tout_usage", "alias": "Farine tout usage"},
        {"canonical_ingredient_id": "pomme_de_terre", "alias": "Pommes de terre"},
        {"canonical_ingredient_id": "banane", "alias": "Banane"},
        {"canonical_ingredient_id": "boeuf_hache", "alias": "Bœuf haché mi-maigre"},
        {"canonical_ingredient_id": "tomate_conserve", "alias": "Tomates en conserve"},
        {"canonical_ingredient_id": "tortilla", "alias": "Tortilla"},
        {"canonical_ingredient_id": "oignon_vert", "alias": "Oignons verts"},
    ]
    (seed / "canonical_ingredients.json").write_text(json.dumps(ingredients), encoding="utf-8")
    (seed / "canonical_ingredient_aliases.json").write_text(json.dumps(aliases), encoding="utf-8")
    return seed


def _write_capture(tmp_path):
    capture = tmp_path / "captures"
    capture.mkdir(parents=True)
    products = [
        {"retailer_product_id": "FLOUR", "name": "Farine tout usage", "brand": "Selection", "package_text": "2.5 kg", "displayed_price": "4.49", "displayed_regular_price": None, "displayed_sale_price": "4.49", "is_promo": True, "in_listing": True},
        {"retailer_product_id": "CHIPS", "name": "Croustilles de pommes de terre", "brand": "Selection", "package_text": "200 g", "displayed_price": "2.00", "in_listing": True},
        {"retailer_product_id": "BANANA", "name": "Banane", "brand": None, "package_text": None, "displayed_price": "0.33", "in_listing": True},
        {"retailer_product_id": "BEEF", "name": "Bœuf haché mi-maigre", "brand": None, "package_text": None, "sale_mode": "variable_weight", "average_package_text": "450 g", "price_variant_text": "450g", "displayed_price": "8.42", "displayed_unit_price": "18.72", "unit_price_reference_quantity": "1", "unit_price_reference_unit": "kg", "in_listing": True},
    ]
    payload = {"captured_at": "2026-08-12T14:00:00-04:00", "products": products}
    (capture / "page.json").write_text(json.dumps(payload), encoding="utf-8")
    return capture


def test_fixed_and_variable_weight_canonical_ingredients_become_products(tmp_path):
    adapter = SuperCCaptureAdapter(
        [_write_capture(tmp_path)],
        _write_seed(tmp_path),
        store_external_key="superc_640",
        week="2026-W32",
        valid_from=date(2026, 8, 6),
        valid_to=date(2026, 8, 12),
    )

    assert [row["external_key"] for row in adapter.product_rows()] == [
        "superc:BEEF",
        "superc:FLOUR",
    ]
    decisions = {row.source_product_id: row for row in adapter.decisions}
    assert decisions["CHIPS"].status == "review"
    assert decisions["CHIPS"].reason == "identity_requires_review"
    assert decisions["BANANA"].status == "review"
    assert decisions["BANANA"].reason == "package_not_fixed_or_unparsed"
    assert decisions["BEEF"].status == "matched"

    beef = next(
        row for row in adapter.product_rows()
        if row["external_key"] == "superc:BEEF"
    )
    assert beef["sale_mode"] == "variable_weight"
    assert beef["package_qty_in_base_unit"] == Decimal("450")
    assert beef["purchase_increment_in_base_unit"] == Decimal("450")
    offer = next(
        item for item in adapter.fetch_week("superc_640", "2026-W32")
        if item.product_external_key == "superc:BEEF"
    )
    assert offer.price_cents_cad == 842
    assert offer.pricing_confidence == "exact"


def test_superc_discount_without_regular_price_is_preserved(tmp_path):
    adapter = SuperCCaptureAdapter(
        [_write_capture(tmp_path)],
        _write_seed(tmp_path),
        store_external_key="superc_640",
        week="2026-W32",
        valid_from=date(2026, 8, 6),
        valid_to=date(2026, 8, 12),
    )
    offer = next(
        item for item in adapter.fetch_week("superc_640", "2026-W32")
        if item.product_external_key == "superc:FLOUR"
    )
    assert offer.product_external_key == "superc:FLOUR"
    assert offer.price_cents_cad == 449
    assert offer.regular_price_cents_cad is None
    assert offer.is_promo is True
    assert "superc:FLOUR" in offer.raw_text
    assert adapter.report()["promotional_products"] == 1


def test_products_outside_recipe_ingredients_are_rejected(tmp_path):
    adapter = SuperCCaptureAdapter(
        [_write_capture(tmp_path)],
        _write_seed(tmp_path),
        store_external_key="superc_640",
        week="2026-W32",
        valid_from=date(2026, 8, 6),
        valid_to=date(2026, 8, 12),
        allowed_canonical_ids={"banane"},
    )

    flour = next(
        decision for decision in adapter.decisions
        if decision.source_product_id == "FLOUR"
    )
    assert flour.status == "rejected"
    assert flour.reason == "not_used_in_recipes"
    assert adapter.product_rows() == []


def test_audited_product_conversion_resolves_volume_to_canonical_mass(tmp_path):
    capture = tmp_path / "conversion-capture"
    capture.mkdir()
    (capture / "page.json").write_text(
        json.dumps(
            {
                "captured_at": "2026-08-13T12:00:00Z",
                "products": [
                    {
                        "retailer_product_id": "TOMATO-796",
                        "name": "Tomates en conserve",
                        "package_text": "796 ml",
                        "displayed_price": "2.49",
                        "in_listing": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    conversion = ProductQuantityConversion(
        canonical_ingredient_id="tomate_conserve",
        from_unit_kind="volume",
        from_base_unit="ml",
        canonical_units_per_source_unit=Decimal("1.01437"),
        confidence="audited_conversion",
        provenance="CNF 2026 food 2462",
    )
    adapter = SuperCCaptureAdapter(
        [capture],
        _write_seed(tmp_path),
        store_external_key="superc_640",
        week="2026-W33",
        valid_from=date(2026, 8, 13),
        valid_to=date(2026, 8, 19),
        product_conversions={"tomate_conserve": (conversion,)},
    )

    row = adapter.product_rows()[0]
    assert row["package_qty_in_base_unit"] == Decimal("807.43852")
    assert row["quantity_confidence"] == "audited_conversion"
    assert row["quantity_provenance"] == "CNF 2026 food 2462"
    offer = adapter.fetch_week("superc_640", "2026-W33")[0]
    assert offer.pricing_confidence == "audited_conversion"


def test_fixed_package_uses_published_count_when_mass_is_also_present(tmp_path):
    capture = tmp_path / "count-and-mass-capture"
    capture.mkdir()
    (capture / "page.json").write_text(
        json.dumps(
            {
                "captured_at": "2026-08-13T12:00:00Z",
                "products": [
                    {
                        "retailer_product_id": "TORTILLA-8",
                        "name": "Tortillas de blé grand format",
                        "package_text": "488 g",
                        "unit_details_text": "8 un - 488 g",
                        "displayed_price": "3.75",
                        "in_listing": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    adapter = SuperCCaptureAdapter(
        [capture],
        _write_seed(tmp_path),
        store_external_key="superc_640",
        week="2026-W33",
        valid_from=date(2026, 8, 13),
        valid_to=date(2026, 8, 19),
        overrides={"TORTILLA-8": "tortilla"},
    )

    row = adapter.product_rows()[0]
    assert row["package_qty_in_base_unit"] == Decimal("8")
    assert row["package_unit"] == "8 un"


def test_multipack_publishes_a_count_as_well_as_a_mass(tmp_path):
    """« 6 x 116 g » dit six articles; ce n'est pas une conversion à inventer."""
    capture = tmp_path / "multipack-capture"
    capture.mkdir()
    (capture / "page.json").write_text(
        json.dumps(
            {
                "captured_at": "2026-08-13T12:00:00Z",
                "products": [
                    {
                        "retailer_product_id": "SUB-6",
                        "name": "Tortilla",
                        "package_text": "6 x 116 g",
                        "displayed_price": "4.99",
                        "in_listing": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    adapter = SuperCCaptureAdapter(
        [capture],
        _write_seed(tmp_path),
        store_external_key="superc_640",
        week="2026-W33",
        valid_from=date(2026, 8, 13),
        valid_to=date(2026, 8, 19),
    )

    row = adapter.product_rows()[0]
    assert row["package_qty_in_base_unit"] == Decimal("6")
    assert row["package_unit"] == "6 un"
    assert row["quantity_confidence"] == "exact"


def _write_bunch_capture(tmp_path, name: str, **overrides) -> object:
    capture = tmp_path / name
    capture.mkdir()
    product = {
        "retailer_product_id": "4068",
        "name": "Oignons verts",
        "package_text": None,
        "unit_details_text": "1 botte",
        "sale_mode": "fixed_package",
        "displayed_price": "1.99",
        "displayed_unit_price": "1.99",
        "unit_price_reference_quantity": "1",
        "unit_price_reference_unit": "ea",
        "in_listing": True,
    }
    product.update(overrides)
    (capture / "page.json").write_text(
        json.dumps({"captured_at": "2026-08-13T12:00:00Z", "products": [product]}),
        encoding="utf-8",
    )
    return capture


def test_produce_sold_by_the_bunch_uses_the_published_single_unit_format(tmp_path):
    """« 1 botte » n'est pas un format lisible; « 1,99 $ / 1 un » en est un."""
    conversion = ProductQuantityConversion(
        canonical_ingredient_id="oignon_vert",
        from_unit_kind="count",
        from_base_unit="unit",
        canonical_units_per_source_unit=Decimal("105"),
        confidence="estimated",
        provenance="FCÉN 2144 (15 g/tige) x 7 tiges par botte, estimation Souschef",
    )
    adapter = SuperCCaptureAdapter(
        [_write_bunch_capture(tmp_path, "bunch-capture")],
        _write_seed(tmp_path),
        store_external_key="superc_640",
        week="2026-W33",
        valid_from=date(2026, 8, 13),
        valid_to=date(2026, 8, 19),
        product_conversions={"oignon_vert": (conversion,)},
    )

    row = adapter.product_rows()[0]
    assert row["package_qty_in_base_unit"] == Decimal("105")
    assert row["quantity_confidence"] == "estimated"
    assert adapter.decisions[0].status == "matched"


def test_comparison_unit_price_is_never_mistaken_for_a_package(tmp_path):
    """Un prix au 100 g décrit une comparaison, jamais la quantité vendue."""
    adapter = SuperCCaptureAdapter(
        [
            _write_bunch_capture(
                tmp_path,
                "comparison-capture",
                displayed_unit_price="10.95",
                unit_price_reference_quantity="100",
                unit_price_reference_unit="g",
            )
        ],
        _write_seed(tmp_path),
        store_external_key="superc_640",
        week="2026-W33",
        valid_from=date(2026, 8, 13),
        valid_to=date(2026, 8, 19),
    )

    assert adapter.product_rows() == []
    assert adapter.decisions[0].reason == "package_not_fixed_or_unparsed"
