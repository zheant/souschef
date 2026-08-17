"""Liste maîtresse rejouable des produits observés chez une bannière."""

from __future__ import annotations

import re
from collections import Counter
from typing import Protocol


class RegistryAdapter(Protocol):
    source_name: str
    source_prefix: str
    decisions: tuple

    def source_products(self) -> dict[str, dict]: ...


def update_product_registry(
    adapter: RegistryAdapter,
    *,
    week: str,
    previous: dict | None = None,
) -> dict:
    """Fusionne une capture dans la liste maîtresse de sa bannière.

    L'identité commerciale est conservée même lorsqu'un produit disparaît :
    il devient inactif et retrouvera son historique s'il réapparaît.
    """
    if not re.fullmatch(r"\d{4}-W\d{2}", week):
        raise ValueError("week doit respecter le format YYYY-Www.")

    products = adapter.source_products()
    decisions = {decision.source_product_id: decision for decision in adapter.decisions}
    missing = sorted(set(products) - decisions.keys())
    extra = sorted(decisions.keys() - set(products))
    if missing:
        raise ValueError(f"Décisions manquantes pour les produits: {missing}")
    if extra:
        raise ValueError(f"Décisions sans produit capturé: {extra}")

    previous_rows = {
        row["source_product_id"]: row
        for row in (previous or {}).get("products", [])
    }
    rows = []
    for source_id, raw in sorted(products.items()):
        decision = decisions[source_id]
        old = previous_rows.get(source_id, {})
        rows.append(
            {
                "source_product_id": source_id,
                "upc": raw.get("upc"),
                "name": str(raw.get("name") or "").strip(),
                "brand": raw.get("brand"),
                "package_text": raw.get("package_text"),
                "unit_details_text": raw.get("unit_details_text"),
                "sale_mode": raw.get("sale_mode", "fixed_package"),
                "average_package_text": raw.get("average_package_text"),
                "purchase_increment": raw.get("purchase_increment"),
                "price_variant_text": raw.get("price_variant_text"),
                "displayed_unit_price": raw.get("displayed_unit_price"),
                "unit_price_reference_quantity": raw.get(
                    "unit_price_reference_quantity"
                ),
                "unit_price_reference_unit": raw.get("unit_price_reference_unit"),
                "category_url": raw.get("category_url"),
                "product_url": raw.get("product_url"),
                "status": decision.status,
                "canonical_ingredient_id": decision.canonical_ingredient_id,
                "candidate_ids": list(decision.candidate_ids),
                "reason": decision.reason,
                "first_seen_week": old.get("first_seen_week", week),
                "last_seen_week": week,
                "active": True,
            }
        )

    for source_id, old in sorted(previous_rows.items()):
        if source_id not in products:
            rows.append({**old, "active": False})

    rows.sort(key=lambda row: row["source_product_id"])
    counts = Counter(
        row["status"] if row["active"] else "inactive" for row in rows
    )
    return {
        "source_name": adapter.source_name,
        "source_prefix": adapter.source_prefix,
        "updated_week": week,
        "counts": dict(sorted(counts.items())),
        "products": rows,
    }


def canonical_gap_candidates(registry: dict) -> list[dict]:
    """Retourne les produits actifs sans aucun candidat canonique connu."""
    return [
        dict(row)
        for row in registry.get("products", [])
        if row.get("active") and row.get("status") == "unmatched"
    ]
