"""Auditer la couverture de prix des recettes depuis des captures locales.

Exemple :
  python scripts/audit_recipe_pricing_coverage.py --week 2026-W33 \
    --superc-root data/catalogue-captures/superc/2026-W33
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
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
    load_title_overrides,
)
from app.adapters.superc_capture import SuperCCaptureAdapter
from app.ingestion.capture_layout import capture_page_dirs_many
from app.services.supply_rules import parse_supply_rules
from app.services.recipe_pricing_coverage import (
    CoverageSupplyRule,
    ProductDecisionEvidence,
    audit_recipe_pricing_coverage,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-dir", type=Path, default=ROOT / "seed" / "main")
    parser.add_argument("--week", required=True, help="Semaine au format YYYY-Www.")
    parser.add_argument("--superc-root", type=Path, action="append")
    parser.add_argument("--maxi-root", type=Path, action="append")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--minimum-complete-recipes", type=int)
    args = parser.parse_args()

    if args.superc_root is None and args.maxi_root is None:
        parser.error("Fournir --superc-root ou --maxi-root.")
    valid_from = _week_thursday(args.week)
    valid_to = date.fromordinal(valid_from.toordinal() + 6)
    decisions = []
    procurement_rules_path = ROOT / "config" / "ingredient-procurement-rules.json"
    product_conversions = load_product_conversions(procurement_rules_path)
    identity_rules = load_identity_rules(ROOT / "config" / "product-identity-rules.json")

    if args.superc_root:
        adapter = SuperCCaptureAdapter(
            capture_page_dirs_many(args.superc_root),
            args.seed_dir,
            store_external_key="superc_640",
            week=args.week,
            valid_from=valid_from,
            valid_to=valid_to,
            overrides=load_match_overrides(
                ROOT / "config" / "superc-match-overrides.json"
            ),
            product_conversions=product_conversions,
            identity_rules=identity_rules,
        )
        decisions.extend(_evidence("superc", adapter.decisions))

    if args.maxi_root:
        adapter = MaxiCaptureAdapter(
            capture_page_dirs_many(args.maxi_root),
            args.seed_dir,
            store_external_key="maxi_7552",
            week=args.week,
            valid_from=valid_from,
            valid_to=valid_to,
            overrides=load_match_overrides(None),
            title_overrides=load_title_overrides(
                ROOT / "config" / "maxi-title-match-overrides.json"
            ),
            product_conversions=product_conversions,
            identity_rules=identity_rules,
        )
        decisions.extend(_evidence("maxi", adapter.decisions))

    recipes = json.loads((args.seed_dir / "recipes.json").read_text(encoding="utf-8"))
    audit = audit_recipe_pricing_coverage(
        recipes,
        decisions,
        supply_rules=_supply_rules(procurement_rules_path),
    )
    payload = audit.as_dict()
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    _print_summary(payload["summary"])
    minimum = args.minimum_complete_recipes
    if minimum is not None and audit.complete_recipes < minimum:
        print(
            f"ÉCHEC: {audit.complete_recipes} recettes complètes, minimum {minimum}.",
            file=sys.stderr,
        )
        return 1
    return 0


def _week_thursday(week: str) -> date:
    try:
        year, number = week.split("-W", 1)
        return date.fromisocalendar(int(year), int(number), 4)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Semaine invalide: {week!r}") from error


def _evidence(source: str, decisions) -> list[ProductDecisionEvidence]:
    return [
        ProductDecisionEvidence(
            source=source,
            status=row.status,
            canonical_ingredient_id=row.canonical_ingredient_id,
            reason=row.reason,
        )
        for row in decisions
    ]


def _supply_rules(path: Path) -> tuple[CoverageSupplyRule, ...]:
    return parse_supply_rules(json.loads(path.read_text(encoding="utf-8")))


def _print_summary(summary: dict) -> None:
    print(
        f"Recettes complètes: {summary['complete_recipes']}/"
        f"{summary['total_recipes']}"
    )
    print(f"Ingrédients distincts: {summary['total_recipe_ingredients']}")
    for status, count in summary["ingredient_status_counts"].items():
        print(f"  {status}: {count}")


if __name__ == "__main__":
    raise SystemExit(main())
