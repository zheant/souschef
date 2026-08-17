"""Classe les titres Maxi indexés vers le canon culinaire Souschef.

L'index public n'est pas une capture de prix et n'offre pas toujours l'UPC.
Les décisions sont donc persistées par titre normalisé. L'adaptateur Maxi les
réappliquera aux vraies captures, dont l'UPC demeure l'identité commerciale.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.ingestion.cnf import parse_cnf_archive  # noqa: E402
from app.ingestion.ingredient_curation import normalize_label  # noqa: E402
from curate_superc_products import build_outputs  # noqa: E402


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _title_id(title: str) -> str:
    normalized = normalize_label(title)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
    return f"maxi-title:{digest}"


def build_registry(source: dict) -> dict:
    by_normalized_title = {}
    for value in source.get("titles", []):
        title = str(value).strip()
        if title:
            by_normalized_title.setdefault(normalize_label(title), title)
    titles = sorted(
        by_normalized_title.values(), key=lambda value: (normalize_label(value), value)
    )
    return {
        "source_name": "Maxi (index public)",
        "source_prefix": "maxi-title",
        "updated_week": "2026-W33",
        "products": [
            {
                "source_product_id": _title_id(title),
                "upc": None,
                "name": title,
                "brand": None,
                "package_text": None,
                "category_url": "/maxi/alimentation/",
                "product_url": None,
                "status": "unmatched",
                "canonical_ingredient_id": None,
                "candidate_ids": [],
                "reason": "official_index_title",
                "active": True,
            }
            for title in titles
        ],
    }


def title_overrides(report: dict) -> list[dict]:
    rows = []
    for decision in report["decisions"]:
        if decision["action"] == "canonical_gap":
            continue
        row = {
            "product_title": decision["product_name"],
            "normalized_title": normalize_label(decision["product_name"]),
            "status": (
                "approved" if decision["action"] == "link_existing" else "rejected"
            ),
            "reason": decision["reason"],
        }
        if decision["canonical_ingredient_id"]:
            row["canonical_ingredient_id"] = decision["canonical_ingredient_id"]
        rows.append(row)
    return sorted(rows, key=lambda row: row["normalized_title"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--titles",
        type=Path,
        default=ROOT / "data/catalogue-registry/maxi-indexed-titles.json",
    )
    parser.add_argument("--seed-dir", type=Path, default=ROOT / "seed/main")
    parser.add_argument(
        "--cnf-archive",
        type=Path,
        default=ROOT / "data/cnf_fcen_all-files-data_2026.zip",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "config/maxi-title-decisions.json"
    )
    parser.add_argument(
        "--overrides",
        type=Path,
        default=ROOT / "config/maxi-title-match-overrides.json",
    )
    parser.add_argument(
        "--gaps",
        type=Path,
        default=ROOT / "data/catalogue-registry/maxi-title-canonical-gaps.json",
    )
    args = parser.parse_args()

    source = _read(args.titles)
    registry = build_registry(source)
    report, _source_id_overrides = build_outputs(
        registry,
        _read(args.seed_dir / "canonical_ingredients.json"),
        _read(args.seed_dir / "canonical_ingredient_aliases.json"),
        parse_cnf_archive(args.cnf_archive),
        rules_version="maxi-indexed-title-curation-v1",
    )
    report["source_kind"] = source.get("source_kind")
    report["source_url"] = source.get("source_url")
    report["completeness"] = source.get("completeness")
    overrides = title_overrides(report)
    _dump(args.output, report)
    _dump(args.overrides, overrides)
    _dump(
        args.gaps,
        [row for row in report["decisions"] if row["action"] == "canonical_gap"],
    )
    print(
        f"Maxi : {report['product_count']} titres; {report['counts']}; "
        f"{len(overrides)} règles de titre actives."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
