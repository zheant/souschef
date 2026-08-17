"""Calculer les devis explicables de toutes les recettes depuis les captures."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.adapters.maxi_capture import (
    MaxiCaptureAdapter,
    load_match_overrides,
    load_identity_rules,
    load_product_conversions,
    load_tax_schedule,
    load_title_overrides,
)
from app.adapters.superc_capture import SuperCCaptureAdapter
from app.ingestion.capture_layout import capture_page_dirs_many
from app.services.recipe_costing import (
    CostingOffer,
    RecipeCostingModule,
    SupplyRule,
)
from app.services.recipe_quality import review_recipes
from app.services.supply_rules import parse_supply_rules


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-dir", type=Path, default=ROOT / "seed" / "main")
    parser.add_argument("--week", required=True)
    parser.add_argument("--superc-root", type=Path, action="append")
    parser.add_argument("--maxi-root", type=Path, action="append")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--minimum-complete-recipes", type=int)
    args = parser.parse_args()
    if args.superc_root is None and args.maxi_root is None:
        parser.error("Fournir --superc-root ou --maxi-root.")

    valid_from = _week_thursday(args.week)
    valid_to = date.fromordinal(valid_from.toordinal() + 6)
    conversions = load_product_conversions(
        ROOT / "config" / "ingredient-procurement-rules.json"
    )
    tax_schedule = load_tax_schedule(ROOT / "config" / "quebec-tax-rates.json")
    identity_rules = load_identity_rules(ROOT / "config" / "product-identity-rules.json")
    adapters = []
    if args.superc_root:
        adapters.append(
            SuperCCaptureAdapter(
                capture_page_dirs_many(args.superc_root),
                args.seed_dir,
                store_external_key="superc_640",
                week=args.week,
                valid_from=valid_from,
                valid_to=valid_to,
                overrides=load_match_overrides(
                    ROOT / "config" / "superc-match-overrides.json"
                ),
                product_conversions=conversions,
                identity_rules=identity_rules,
                tax_schedule=tax_schedule,
            )
        )
    if args.maxi_root:
        adapters.append(
            MaxiCaptureAdapter(
                capture_page_dirs_many(args.maxi_root),
                args.seed_dir,
                store_external_key="maxi_7552",
                week=args.week,
                valid_from=valid_from,
                valid_to=valid_to,
                title_overrides=load_title_overrides(
                    ROOT / "config" / "maxi-title-match-overrides.json"
                ),
                product_conversions=conversions,
                identity_rules=identity_rules,
                tax_schedule=tax_schedule,
            )
        )

    offers = [offer for adapter in adapters for offer in _costing_offers(adapter)]
    recipes = json.loads((args.seed_dir / "recipes.json").read_text(encoding="utf-8"))
    rules = _supply_rules(ROOT / "config" / "ingredient-procurement-rules.json")
    quotes = RecipeCostingModule.quote_all(
        recipes, offers, supply_rules=rules, staples=_staples(args.seed_dir)
    )
    canonical = json.loads(
        (args.seed_dir / "canonical_ingredients.json").read_text(encoding="utf-8")
    )
    # Un devis complet n'est pas un devis fiable : la recette elle-même peut
    # demander « 1 g d'aubergine ». Le défaut voyage avec le devis, sinon
    # l'affichage n'a aucun moyen de le savoir.
    flags = review_recipes(recipes, canonical)
    rows = []
    for quote in quotes:
        row = quote.as_dict()
        row["quality_flags"] = [
            {"kind": flag.kind, "subject": flag.subject, "detail": flag.detail}
            for flag in flags.get(quote.recipe_id, ())
        ]
        rows.append(row)
    referenced = {
        key
        for quote in quotes
        for key in [line.product_external_key for line in quote.ingredients]
        + [line.product_external_key for line in quote.purchases]
        if key
    }
    payload = {
        "week": args.week,
        "products": _product_index(adapters, offers, referenced),
        "complete_recipes": sum(quote.status == "complete" for quote in quotes),
        "reliable_recipes": sum(
            quote.status == "complete" and not flags.get(quote.recipe_id)
            for quote in quotes
        ),
        "total_recipes": len(quotes),
        "quotes": rows,
    }
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    print(
        f"Devis complets: {payload['complete_recipes']}/{payload['total_recipes']}"
        f" dont fiables: {payload['reliable_recipes']}"
    )
    for quote in quotes:
        if quote.status == "complete":
            print(
                f"  {quote.recipe_id}: {quote.consumed_cost_cents} c consommés; "
                f"{quote.autonomous_checkout_cents} c à décaisser; "
                f"confiance={quote.consumed_confidence}/{quote.checkout_confidence}"
            )
    minimum = args.minimum_complete_recipes
    return 1 if minimum is not None and payload["complete_recipes"] < minimum else 0


def _costing_offers(adapter) -> list[CostingOffer]:
    products = {row["external_key"]: row for row in adapter.product_rows()}
    result = []
    for offer in adapter.fetch_week(adapter.store_external_key, adapter.week):
        product = products[offer.product_external_key]
        result.append(
            CostingOffer(
                product_external_key=offer.product_external_key,
                canonical_ingredient_id=product["canonical_ingredient_id"],
                store_external_key=offer.store_external_key,
                quantity_in_base_unit=Decimal(product["package_qty_in_base_unit"]),
                price_cents_cad=offer.price_cents_cad,
                tax_rate=Decimal(product["tax_rate"]),
                regular_price_cents_cad=offer.regular_price_cents_cad,
                is_promo=offer.is_promo,
                sale_mode=product.get("sale_mode", "fixed_package"),
                purchase_increment_in_base_unit=product.get(
                    "purchase_increment_in_base_unit"
                ),
                valid_from=offer.valid_from,
                valid_to=offer.valid_to,
                confidence=offer.pricing_confidence,
            )
        )
    return result


def _product_index(adapters, offers, referenced: set[str]) -> dict:
    """Identité commerciale des produits cités par les devis.

    Le rapport doit se suffire à lui-même : un lecteur qui remonte d'un total
    vers un produit ne doit pas avoir besoin du registre de curation ni des
    captures pour savoir de quel article et de quel format il s'agit.
    """
    priced = {offer.product_external_key: offer for offer in offers}
    index: dict[str, dict] = {}
    for adapter in adapters:
        sources = adapter.source_products()
        for row in adapter.product_rows():
            key = row["external_key"]
            if key not in referenced:
                continue
            source_id = key.split(":", 1)[1]
            raw = sources.get(source_id, {})
            offer = priced.get(key)
            index[key] = {
                "name": raw.get("name"),
                "price_cents_cad": offer.price_cents_cad if offer else None,
                "regular_price_cents_cad": (
                    offer.regular_price_cents_cad if offer else None
                ),
                "is_promo": bool(offer.is_promo) if offer else False,
                "brand": row.get("brand"),
                "package_unit": row.get("package_unit"),
                "package_qty_in_base_unit": row.get("package_qty_in_base_unit"),
                "sale_mode": row.get("sale_mode"),
                "quantity_confidence": row.get("quantity_confidence"),
                "quantity_provenance": row.get("quantity_provenance"),
                "tax_rate": row.get("tax_rate"),
                "store_external_key": adapter.store_external_key,
            }
    return dict(sorted(index.items()))


def _supply_rules(path: Path) -> list[SupplyRule]:
    return list(parse_supply_rules(json.loads(path.read_text(encoding="utf-8"))))


def _staples(seed_dir: Path) -> list[str]:
    """Essentiels du ménage, lus dans le seed plutôt que recopiés à la main.

    Le rapport hors ligne et la route HTTP doivent nommer les mêmes essentiels;
    la seule façon d'en être sûr est de lire la même déclaration, chacun là où
    elle vit — la table `household.staple` pour l'API, ce fichier pour le
    rapport, tous deux alimentés par le même seed.
    """
    payload = json.loads((seed_dir / "household.json").read_text(encoding="utf-8"))
    return sorted(str(item) for item in payload.get("staples", []))


def _week_thursday(week: str) -> date:
    try:
        year, number = week.split("-W", 1)
        return date.fromisocalendar(int(year), int(number), 4)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Semaine invalide: {week!r}") from error


if __name__ == "__main__":
    raise SystemExit(main())
