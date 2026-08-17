"""Liste maîtresse durable des produits capturés par bannière."""

from dataclasses import dataclass

from app.ingestion.product_registry import (
    canonical_gap_candidates,
    update_product_registry,
)


@dataclass(frozen=True)
class _Decision:
    source_product_id: str
    product_name: str
    status: str
    canonical_ingredient_id: str | None
    candidate_ids: tuple[str, ...]
    reason: str


class _Adapter:
    source_name = "Super C"
    source_prefix = "superc"

    def __init__(self, products, decisions):
        self._products = products
        self.decisions = decisions

    def source_products(self):
        return self._products


def test_registry_keeps_identity_mapping_and_lifecycle_across_weeks():
    first = _Adapter(
        {
            "111": {
                "upc": "111",
                "name": "Pommes biologiques",
                "brand": None,
                "package_text": "3 lb",
                "category_url": "/allees/fruits-et-legumes/fruits",
                "product_url": "https://superc.test/pommes/p/111",
            }
        },
        (
            _Decision(
                "111", "Pommes biologiques", "matched", "pomme",
                ("pomme",), "exact_canonical_alias"
            ),
        ),
    )
    w32 = update_product_registry(first, week="2026-W32")

    assert w32["counts"] == {"matched": 1}
    assert w32["products"][0] == {
        "source_product_id": "111",
        "upc": "111",
        "name": "Pommes biologiques",
        "brand": None,
        "package_text": "3 lb",
        "unit_details_text": None,
        "sale_mode": "fixed_package",
        "average_package_text": None,
        "purchase_increment": None,
        "price_variant_text": None,
        "displayed_unit_price": None,
        "unit_price_reference_quantity": None,
        "unit_price_reference_unit": None,
        "category_url": "/allees/fruits-et-legumes/fruits",
        "product_url": "https://superc.test/pommes/p/111",
        "status": "matched",
        "canonical_ingredient_id": "pomme",
        "candidate_ids": ["pomme"],
        "reason": "exact_canonical_alias",
        "first_seen_week": "2026-W32",
        "last_seen_week": "2026-W32",
        "active": True,
    }

    second = _Adapter(
        {
            "222": {
                "upc": "222",
                "name": "Macaroni au fromage",
                "brand": "Test",
                "package_text": "225 g",
                "category_url": "/allees/garde-manger/pates-riz-et-feves",
                "product_url": "https://superc.test/macaroni/p/222",
            }
        },
        (
            _Decision(
                "222", "Macaroni au fromage", "review", None,
                ("macaroni",), "identity_requires_review"
            ),
        ),
    )
    w33 = update_product_registry(second, week="2026-W33", previous=w32)

    rows = {row["source_product_id"]: row for row in w33["products"]}
    assert rows["111"]["active"] is False
    assert rows["111"]["last_seen_week"] == "2026-W32"
    assert rows["222"]["active"] is True
    assert rows["222"]["first_seen_week"] == "2026-W33"
    assert w33["counts"] == {"inactive": 1, "review": 1}


def test_gap_candidates_exclude_confirmed_and_rejected_products():
    adapter = _Adapter(
        {
            "1": {"name": "Pommes", "upc": "1"},
            "2": {"name": "Produit inconnu", "upc": "2"},
            "3": {"name": "Croustilles", "upc": "3"},
        },
        (
            _Decision("1", "Pommes", "matched", "pomme", ("pomme",), "exact"),
            _Decision("2", "Produit inconnu", "unmatched", None, (), "no_alias"),
            _Decision("3", "Croustilles", "rejected", None, (), "human_rejected"),
        ),
    )

    registry = update_product_registry(adapter, week="2026-W33")
    gaps = canonical_gap_candidates(registry)

    assert [row["source_product_id"] for row in gaps] == ["2"]


def test_registry_requires_one_decision_per_captured_product():
    adapter = _Adapter({"1": {"name": "Pommes"}}, ())

    try:
        update_product_registry(adapter, week="2026-W33")
    except ValueError as error:
        assert "Décisions manquantes" in str(error)
    else:
        raise AssertionError("Un produit sans décision doit être refusé.")
