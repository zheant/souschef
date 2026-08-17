"""Adaptation des captures Maxi au canon et aux DTO de Souschef."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from app.adapters.maxi_capture import MaxiCaptureAdapter


def _write_seed(tmp_path):
    seed = tmp_path / "seed"
    seed.mkdir(parents=True)
    ingredients = [
        {"id": "beurre", "name": "Beurre salé", "unit_kind": "mass", "base_unit": "g"},
        {"id": "beurre_non_sale", "name": "Beurre non salé", "unit_kind": "mass", "base_unit": "g"},
        {"id": "beurre_arachide", "name": "Beurre d'arachide", "unit_kind": "mass", "base_unit": "g"},
        {"id": "beurre_non_precise", "name": "Beurre non précisé", "unit_kind": "mass", "base_unit": "g"},
        {"id": "oeuf", "name": "Œuf de calibre gros", "unit_kind": "count", "base_unit": "unit"},
        {"id": "poulet_poitrine", "name": "Poitrines de poulet", "unit_kind": "mass", "base_unit": "g"},
    ]
    aliases = [
        {"canonical_ingredient_id": "beurre", "alias": "Salted butter"},
        {"canonical_ingredient_id": "beurre_non_sale", "alias": "Unsalted butter"},
        {"canonical_ingredient_id": "beurre_arachide", "alias": "Peanut butter"},
        {"canonical_ingredient_id": "beurre_non_precise", "alias": "Butter"},
        {"canonical_ingredient_id": "oeuf", "alias": "Large egg"},
        {"canonical_ingredient_id": "poulet_poitrine", "alias": "Chicken breasts"},
    ]
    (seed / "canonical_ingredients.json").write_text(json.dumps(ingredients), encoding="utf-8")
    (seed / "canonical_ingredient_aliases.json").write_text(json.dumps(aliases), encoding="utf-8")
    return seed


def _write_capture(tmp_path):
    capture = tmp_path / "captures"
    capture.mkdir(parents=True)
    products = [
        {"retailer_product_id": "BUTTER-454", "name": "Unsalted Butter", "brand": "No Name", "package_text": "454 g, $1.36/100g", "displayed_price": "6.19", "displayed_regular_price": "7.49", "displayed_sale_price": "6.19", "product_url": "https://maxi.test/butter", "in_listing": True},
        {"retailer_product_id": "PEANUT-1KG", "name": "Smooth Peanut Butter", "brand": "No Name", "package_text": "1 kg, $0.60/100g", "displayed_price": "6.00", "product_url": "https://maxi.test/peanut", "in_listing": True},
        {"retailer_product_id": "BUNS-300", "name": "All-Butter Brioche Buns", "brand": "Test", "package_text": "300 g, $1.67/100g", "displayed_price": "5.00", "product_url": "https://maxi.test/buns", "in_listing": True},
        {"retailer_product_id": "EGGS-12", "name": "Large Size Eggs 12 Pack", "brand": "No Name", "package_text": "12 ea, $0.35/1ea", "displayed_price": "4.20", "product_url": "https://maxi.test/eggs", "in_listing": True},
        {"retailer_product_id": "BUTTER-VAR", "name": "Salted Butter", "brand": "Test", "package_text": "$6.59/1kg", "displayed_price": "6.59", "product_url": "https://maxi.test/variable", "in_listing": True},
        {"retailer_product_id": "CHICKEN-500", "name": "Chicken Breast Boneless Skinless Club Pack", "brand": "Test", "package_text": "500 g, $1.50/100g", "displayed_price": "7.50", "product_url": "https://maxi.test/chicken", "in_listing": True},
    ]
    page = {"captured_at": "2026-08-03T20:11:33-04:00", "products": products}
    (capture / "page.json").write_text(json.dumps(page), encoding="utf-8")
    return capture


def _adapter(tmp_path, **kwargs):
    return MaxiCaptureAdapter(
        [_write_capture(tmp_path)],
        _write_seed(tmp_path),
        store_external_key="maxi_7552",
        week="2026-W32",
        valid_from=date(2026, 8, 6),
        valid_to=date(2026, 8, 12),
        **kwargs,
    )


def test_uses_souschef_slugs_and_keeps_multiple_precise_products(tmp_path):
    adapter = _adapter(tmp_path)
    rows = {row["external_key"]: row for row in adapter.product_rows()}

    assert rows["maxi:BUTTER-454"]["canonical_ingredient_id"] == "beurre_non_sale"
    assert rows["maxi:PEANUT-1KG"]["canonical_ingredient_id"] == "beurre_arachide"
    assert rows["maxi:EGGS-12"]["canonical_ingredient_id"] == "oeuf"
    assert rows["maxi:CHICKEN-500"]["canonical_ingredient_id"] == "poulet_poitrine"
    assert rows["maxi:EGGS-12"]["package_qty_in_base_unit"] == Decimal("12")
    assert all("INGREDIENT_" not in row["canonical_ingredient_id"] for row in rows.values())


def test_compound_food_and_variable_weight_are_not_imported(tmp_path):
    adapter = _adapter(tmp_path)
    decisions = {row.source_product_id: row for row in adapter.decisions}

    assert decisions["BUNS-300"].status == "review"
    assert decisions["BUNS-300"].reason == "identity_requires_review"
    assert decisions["BUTTER-VAR"].status == "review"
    assert decisions["BUTTER-VAR"].reason == "package_not_fixed_or_unparsed"
    assert len(adapter.product_rows()) == 4


def test_prices_follow_the_existing_raw_offer_contract(tmp_path):
    adapter = _adapter(tmp_path)
    offers = {offer.product_external_key: offer for offer in adapter.fetch_week("maxi_7552", "2026-W32")}

    butter = offers["maxi:BUTTER-454"]
    assert butter.price_cents_cad == 619
    assert butter.regular_price_cents_cad == 749
    assert butter.is_promo is True
    assert butter.valid_from == "2026-08-06"
    assert adapter.fetch_week("another_store", "2026-W32") == []


def test_human_override_must_target_a_souschef_slug(tmp_path):
    adapter = _adapter(tmp_path, overrides={"BUNS-300": "beurre"})
    decisions = {row.source_product_id: row for row in adapter.decisions}
    assert decisions["BUNS-300"].status == "matched"
    assert decisions["BUNS-300"].canonical_ingredient_id == "beurre"

    try:
        _adapter(tmp_path / "unknown", overrides={"BUNS-300": "INGREDIENT_012"})
    except ValueError as error:
        assert "Slugs canoniques inconnus" in str(error)
    else:
        raise AssertionError("Un ancien identifiant ne doit jamais être accepté.")


def test_title_override_is_reused_for_a_new_retailer_product_id(tmp_path):
    adapter = _adapter(
        tmp_path,
        title_overrides={"all butter brioche buns": "beurre"},
    )
    decisions = {row.source_product_id: row for row in adapter.decisions}

    assert decisions["BUNS-300"].status == "matched"
    assert decisions["BUNS-300"].canonical_ingredient_id == "beurre"
    assert decisions["BUNS-300"].reason == "human_title_approved"


def test_deduplication_keeps_promotion_and_enriches_its_quantity_proof(tmp_path):
    capture = tmp_path / "duplicate-captures"
    capture.mkdir()
    base = {
        "retailer_product_id": "BUTTER-454",
        "name": "Unsalted Butter",
        "brand": "No Name",
        "package_text": "454 g",
        "displayed_price": "7.49",
        "product_url": "https://maxi.test/butter",
        "in_listing": True,
    }
    deal = {
        "retailer_product_id": "BUTTER-454",
        "name": "Unsalted Butter",
        "displayed_price": "6.19",
        "displayed_regular_price": "7.49",
        "displayed_sale_price": "6.19",
        "is_promo": True,
        "in_listing": True,
    }
    (capture / "category.json").write_text(
        json.dumps({"captured_at": "2026-08-13T12:00:00Z", "products": [base]}),
        encoding="utf-8",
    )
    (capture / "deals.json").write_text(
        json.dumps({"captured_at": "2026-08-13T11:00:00Z", "products": [deal]}),
        encoding="utf-8",
    )

    adapter = MaxiCaptureAdapter(
        [capture],
        _write_seed(tmp_path),
        store_external_key="maxi_7552",
        week="2026-W33",
        valid_from=date(2026, 8, 13),
        valid_to=date(2026, 8, 19),
    )

    product = adapter.source_products()["BUTTER-454"]
    assert product["is_promo"] is True
    assert product["displayed_price"] == "6.19"
    assert product["package_text"] == "454 g"
    assert product["brand"] == "No Name"
