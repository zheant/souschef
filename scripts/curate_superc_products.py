"""Produit les décisions durables Super C -> canon culinaire.

Le manifeste complet conserve une décision pour chaque UPC observé. Le fichier
d'overrides, consommé par l'adaptateur hebdomadaire, ne contient que les liens
et exclusions définitifs; une lacune canonique reste donc visible à la
prochaine capture au lieu d'être silencieusement rejetée.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.ingestion.cnf import parse_cnf_archive  # noqa: E402
from app.ingestion.ingredient_curation import normalize_label  # noqa: E402
from app.ingestion.retail_product_curation import (  # noqa: E402
    CanonicalIndex,
    classify_product,
)

_CNF_GROUPS = frozenset({"1", "2", "4", "5", "9", "10", "11", "12", "13", "15", "16", "17", "20"})
_STOPWORDS = frozenset(
    {
        "a", "au", "aux", "avec", "de", "des", "du", "en", "et", "la",
        "le", "les", "sans", "sur", "pour", "produit", "produits", "frais",
        "fraiche", "frais", "biologique", "format", "fromage", "pate",
    }
)


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in normalize_label(value).split()
        if len(token) > 2 and token not in _STOPWORDS
    }


def _cnf_index(rows: tuple[dict, ...]):
    index: dict[str, set[int]] = defaultdict(set)
    eligible: list[dict] = []
    for row in rows:
        if row["cnf_food_group_code"] not in _CNF_GROUPS:
            continue
        position = len(eligible)
        eligible.append(row)
        for token in _tokens(row["food_description_fr"]):
            index[token].add(position)
    return eligible, index


def _cnf_candidates(name: str, eligible: list[dict], token_index) -> list[dict]:
    wanted = _tokens(name)
    positions: set[int] = set()
    for token in wanted:
        positions.update(token_index.get(token, ()))
    scored = []
    normalized = normalize_label(name)
    for position in positions:
        row = eligible[position]
        candidate = _tokens(row["food_description_fr"])
        overlap = len(wanted & candidate) / max(1, len(wanted | candidate))
        sequence = SequenceMatcher(
            None, normalized, normalize_label(row["food_description_fr"])
        ).ratio()
        score = 0.65 * overlap + 0.35 * sequence
        scored.append((score, row))
    result = []
    for score, row in sorted(
        scored,
        key=lambda item: (item[0], item[1]["food_code"]),
        reverse=True,
    ):
        if score < 0.35 or len(result) == 3:
            break
        result.append(
            {
                "food_code": row["food_code"],
                "food_description_fr": row["food_description_fr"],
                "food_description_en": row["food_description_en"],
                "cnf_food_group_code": row["cnf_food_group_code"],
                "score": round(score, 3),
            }
        )
    return result


def build_outputs(
    registry: dict,
    ingredients: list[dict],
    aliases: list[dict],
    cnf,
    *,
    rules_version: str = "superc-product-curation-v1",
    reviewed_overrides: list[dict] | None = None,
):
    canonical = CanonicalIndex.from_rows(ingredients, aliases)
    eligible, cnf_token_index = _cnf_index(cnf.rows)
    reviewed_by_id = {
        row["source_product_id"]: row for row in (reviewed_overrides or [])
    }
    decisions = []
    overrides = []
    for product in sorted(registry["products"], key=lambda row: row["source_product_id"]):
        decision = classify_product(product, canonical)
        row = {
            "source_product_id": decision.source_product_id,
            "upc": product.get("upc"),
            "product_name": decision.product_name,
            "brand": product.get("brand"),
            "category_url": product.get("category_url"),
            "product_url": product.get("product_url"),
            **decision.as_dict(),
        }
        reviewed = reviewed_by_id.get(decision.source_product_id)
        if reviewed is not None:
            approved = reviewed["status"] == "approved"
            row.update(
                action="link_existing" if approved else "exclude",
                canonical_ingredient_id=(
                    reviewed.get("canonical_ingredient_id") if approved else None
                ),
                reason=reviewed.get("reason", "human_review"),
                confidence="human_review",
                evidence=["superc-match-overrides.json"],
            )
        if row["action"] == "canonical_gap":
            row["cnf_candidates"] = _cnf_candidates(
                decision.product_name, eligible, cnf_token_index
            )
        decisions.append(row)
        if row["action"] == "link_existing":
            overrides.append(
                {
                    "source_product_id": decision.source_product_id,
                    "status": "approved",
                    "canonical_ingredient_id": row["canonical_ingredient_id"],
                    "reason": row["reason"],
                }
            )
        elif row["action"] == "exclude":
            overrides.append(
                {
                    "source_product_id": decision.source_product_id,
                    "status": "rejected",
                    "reason": row["reason"],
                }
            )
    registry_ids = {row["source_product_id"] for row in registry["products"]}
    overrides.extend(
        dict(row)
        for row in (reviewed_overrides or [])
        if row["source_product_id"] not in registry_ids
    )
    overrides.sort(key=lambda row: row["source_product_id"])
    counts = dict(sorted(Counter(row["action"] for row in decisions).items()))
    report = {
        "source_name": registry["source_name"],
        "source_week": registry["updated_week"],
        "rules_version": rules_version,
        "cnf_archive_sha256": cnf.archive_sha256,
        "canonical_ingredient_count": len(ingredients),
        "product_count": len(decisions),
        "counts": counts,
        "decisions": decisions,
    }
    return report, overrides


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=ROOT / "data/catalogue-registry/superc.json")
    parser.add_argument("--seed-dir", type=Path, default=ROOT / "seed/main")
    parser.add_argument("--cnf-archive", type=Path, default=ROOT / "data/cnf_fcen_all-files-data_2026.zip")
    parser.add_argument("--output", type=Path, default=ROOT / "config/superc-product-decisions.json")
    parser.add_argument("--overrides", type=Path, default=ROOT / "config/superc-match-overrides.json")
    parser.add_argument(
        "--reviewed-overrides",
        type=Path,
        default=ROOT / "config/superc-reviewed-overrides.json",
    )
    parser.add_argument("--gaps", type=Path, default=ROOT / "data/catalogue-registry/superc-canonical-gaps.json")
    args = parser.parse_args()

    registry = _read(args.registry)
    ingredients = _read(args.seed_dir / "canonical_ingredients.json")
    aliases = _read(args.seed_dir / "canonical_ingredient_aliases.json")
    cnf = parse_cnf_archive(args.cnf_archive)
    reviewed_overrides = (
        _read(args.reviewed_overrides) if args.reviewed_overrides.exists() else []
    )
    report, overrides = build_outputs(
        registry,
        ingredients,
        aliases,
        cnf,
        reviewed_overrides=reviewed_overrides,
    )
    _dump(args.output, report)
    _dump(args.overrides, overrides)
    _dump(
        args.gaps,
        [row for row in report["decisions"] if row["action"] == "canonical_gap"],
    )
    print(
        f"Super C : {report['product_count']} décisions; "
        f"{report['counts']}; {len(overrides)} overrides actifs."
    )


if __name__ == "__main__":
    main()
