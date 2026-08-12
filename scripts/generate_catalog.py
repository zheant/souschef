"""Régénère uniquement les fichiers versionnés du catalogue canonique."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from catalog_seed_data import (
    alias_rows,
    family_rows,
    ingredient_rows,
    normalize_label,
)

ROOT = Path(__file__).resolve().parent.parent


def dump(path: Path, rows: list[dict]) -> None:
    path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _curation_rows(seed: Path) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    curation_path = seed / "cnf_catalog_curation.json"
    if not curation_path.exists():
        return [], [], [], []
    batch = json.loads(curation_path.read_text(encoding="utf-8"))
    ingredients: list[dict] = []
    aliases: list[dict] = []
    external_refs: list[dict] = []
    events: list[dict] = []
    for decision in batch["decisions"]:
        canonical = decision.get("canonical")
        target = (
            canonical["id"]
            if decision["action"] == "create_variant"
            else decision["canonical_ingredient_id"]
        )
        if canonical is not None:
            ingredients.append(canonical)
        for alias in decision.get("aliases", []):
            aliases.append(
                {
                    "canonical_ingredient_id": target,
                    "language": alias["language"],
                    "alias": alias["alias"],
                    "normalized_alias": normalize_label(alias["alias"]),
                    "source": "cnf",
                    "source_version": decision["source_version"],
                    "confirmed_by": decision["reviewer"],
                }
            )
        external_refs.append(
            {
                "canonical_ingredient_id": target,
                "source": "cnf",
                "external_id": decision["food_code"],
                "source_version": decision["source_version"],
                "notes": decision["rationale"],
            }
        )
        payload = {
            "source_version": decision["source_version"],
            "food_code": decision["food_code"],
            "action": decision["action"],
            "reviewer": decision["reviewer"],
            "rationale": decision["rationale"],
            "canonical_ingredient_id": decision.get("canonical_ingredient_id"),
            "canonical": canonical,
            "aliases": decision.get("aliases", []),
            "acknowledged_similar_ids": decision.get(
                "acknowledged_similar_ids", []
            ),
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest().upper()
        events.append(
            {
                "decision_fingerprint": fingerprint,
                "source": "cnf",
                "source_version": decision["source_version"],
                "external_id": decision["food_code"],
                "source_archive_sha256": decision["archive_sha256"],
                "action": decision["action"],
                "canonical_ingredient_id": target,
                "reviewer": decision["reviewer"],
                "rationale": decision["rationale"],
                "decision_payload": payload,
                "candidate_snapshot": decision["candidate_snapshot"],
            }
        )
    return ingredients, aliases, external_refs, events


def main() -> None:
    seed = ROOT / "seed" / "main"
    additions, added_aliases, external_refs, events = _curation_rows(seed)
    ingredients = [*ingredient_rows(), *additions]
    # La curation FCÉN ne possède pas les paramètres métier du solveur. Lors
    # d'une régénération isolée du catalogue, préserver les rares valeurs déjà
    # calibrées dans le seed versionné plutôt que de les effacer.
    existing_path = seed / "canonical_ingredients.json"
    if existing_path.exists():
        existing = {
            row["id"]: row
            for row in json.loads(existing_path.read_text(encoding="utf-8"))
        }
        for row in ingredients:
            prior = existing.get(row["id"])
            if prior is not None:
                row["perishability"] = prior.get("perishability")
                row["salvage_value_cents_per_base_unit"] = prior.get(
                    "salvage_value_cents_per_base_unit"
                )
    aliases = [*alias_rows(), *added_aliases]
    dump(seed / "ingredient_families.json", family_rows())
    dump(seed / "canonical_ingredients.json", ingredients)
    dump(seed / "canonical_ingredient_aliases.json", aliases)
    dump(seed / "canonical_ingredient_external_refs.json", external_refs)
    dump(seed / "ingredient_curation_events.json", events)
    print(
        f"Catalogue : {len(family_rows())} familles, "
        f"{len(ingredients)} ingrédients, {len(aliases)} alias, "
        f"{len(external_refs)} références FCÉN."
    )


if __name__ == "__main__":
    main()
