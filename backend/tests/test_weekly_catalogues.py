"""Gardes de période du lancement hebdomadaire."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_weekly_catalogues.py"
SPEC = importlib.util.spec_from_file_location("run_weekly_catalogues", SCRIPT)
weekly = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = weekly
SPEC.loader.exec_module(weekly)


def test_period_is_the_current_thursday_to_wednesday_circular():
    wednesday = weekly.circular_period(date(2026, 8, 12))
    thursday = weekly.circular_period(date(2026, 8, 13))

    assert wednesday.week == "2026-W32"
    assert wednesday.valid_from == date(2026, 8, 6)
    assert wednesday.valid_to == date(2026, 8, 12)
    assert thursday.week == "2026-W33"
    assert thursday.valid_from == date(2026, 8, 13)


def test_old_maxi_capture_cannot_be_relabelled_as_current_week(tmp_path):
    capture = tmp_path / "maxi"
    capture.mkdir()
    (capture / "page.json").write_text(
        json.dumps({"captured_at": "2026-08-05T23:30:00-04:00", "products": []}),
        encoding="utf-8",
    )

    try:
        weekly._validate_current_captures(
            [capture], weekly.circular_period(date(2026, 8, 12)), "Maxi"
        )
    except ValueError as error:
        assert "hors de 2026-08-06..2026-08-12" in str(error)
    else:
        raise AssertionError("Une vieille capture Maxi ne doit pas être relabellée.")


def test_superc_proxies_are_loaded_from_a_json_environment_variable(monkeypatch):
    monkeypatch.setenv(
        "SOUSCHEF_SUPERC_PROXIES",
        '["http://proxy-1.test:8080", "https://proxy-2.test:8443"]',
    )

    assert weekly._configured_proxies(
        {"proxy_environment_variable": "SOUSCHEF_SUPERC_PROXIES"}
    ) == ["http://proxy-1.test:8080", "https://proxy-2.test:8443"]


def test_capture_jobs_start_sources_concurrently(tmp_path):
    barrier = threading.Barrier(2, timeout=2)
    started = []

    def capture(name):
        def run():
            started.append(name)
            barrier.wait()
            time.sleep(0.01)
            return weekly.CaptureResult((tmp_path,), (), 1, 1, True, False)

        return run

    results = weekly._run_capture_jobs(
        {"maxi": capture("maxi"), "superc": capture("superc")}
    )

    assert set(started) == {"maxi", "superc"}
    assert set(results) == {"maxi", "superc"}


def test_reuse_ignores_diagnostic_runs(tmp_path):
    diagnostic = tmp_path / "run-20260813T120000Z"
    diagnostic.mkdir()
    (diagnostic / "_complete.json").write_text(
        json.dumps(
            {
                "complete_catalogue": False,
                "categories": ["diagnostic"],
                "pages_captured": 1,
                "rows_captured_before_deduplication": 40,
            }
        ),
        encoding="utf-8",
    )

    try:
        weekly._reuse_capture(tmp_path, "Maxi")
    except FileNotFoundError as error:
        assert "Aucune exécution Maxi complète" in str(error)
    else:
        raise AssertionError("Une capture limitée ne doit jamais être rejouée comme complète.")


def test_reuse_ignores_old_complete_runs_without_weekly_deals(tmp_path):
    old_run = tmp_path / "run-20260813T120000Z"
    capture = old_run / "category"
    capture.mkdir(parents=True)
    (capture / "page-001.json").write_text(
        json.dumps({"captured_at": "2026-08-13T12:00:00Z", "products": []}),
        encoding="utf-8",
    )
    (old_run / "_complete.json").write_text(
        json.dumps(
            {
                "complete_catalogue": True,
                "categories": ["category"],
                "pages_captured": 1,
                "rows_captured_before_deduplication": 0,
            }
        ),
        encoding="utf-8",
    )

    try:
        weekly._reuse_capture(tmp_path, "Maxi")
    except FileNotFoundError as error:
        assert "Aucune exécution Maxi complète" in str(error)
    else:
        raise AssertionError("Une ancienne capture sans rabais ne doit pas être rejouée.")


def test_complete_manifest_records_weekly_deal_targets(tmp_path):
    weekly._write_complete_manifest(
        tmp_path,
        ("category", "weekly-deals"),
        2,
        10,
        True,
        ("weekly-deals",),
        8,
        7,
    )

    manifest = json.loads((tmp_path / "_complete.json").read_text(encoding="utf-8"))
    assert manifest["deal_targets"] == ["weekly-deals"]
    assert manifest["deal_products_captured"] == 8
    assert manifest["deal_promotions_captured"] == 7
    assert weekly._is_reusable_capture(tmp_path) is True


def test_weekly_deal_capture_requires_at_least_one_promotion():
    pages = [{"products": [{"is_promo": True}, {"is_promo": False}]}]
    assert weekly._deal_capture_counts("Super C", pages) == (2, 1)

    try:
        weekly._deal_capture_counts("Maxi", [{"products": [{"is_promo": False}]}])
    except RuntimeError as error:
        assert "sans prix promotionnel" in str(error)
    else:
        raise AssertionError("Une page sans promotion ne doit pas valider le passage.")


def test_complete_capture_rejects_an_implausibly_small_catalogue():
    try:
        weekly._validate_capture_scale(
            "Maxi", 1, {"minimum_distinct_products": 500}, True
        )
    except RuntimeError as error:
        assert "1 produits distincts" in str(error)
    else:
        raise AssertionError("Le catalogue Maxi à un produit devait être refusé.")

    weekly._validate_capture_scale(
        "diagnostic", 1, {"minimum_distinct_products": 500}, False
    )


@dataclass(frozen=True)
class _Decision:
    source_product_id: str
    product_name: str
    status: str
    canonical_ingredient_id: str | None
    candidate_ids: tuple[str, ...]
    reason: str


class _RegistryAdapter:
    source_name = "Super C"
    source_prefix = "superc"
    decisions = (
        _Decision("1", "Pommes", "matched", "pomme", ("pomme",), "exact"),
        _Decision("2", "Produit inconnu", "unmatched", None, (), "no_alias"),
    )

    def source_products(self):
        return {
            "1": {"name": "Pommes", "upc": "1"},
            "2": {"name": "Produit inconnu", "upc": "2"},
        }


def test_complete_capture_writes_registry_and_canonical_gaps(tmp_path):
    paths = weekly._write_registry_files(
        _RegistryAdapter(), tmp_path, "2026-W33"
    )

    registry = json.loads(Path(paths["registry_path"]).read_text(encoding="utf-8"))
    gaps = json.loads(
        Path(paths["canonical_gaps_path"]).read_text(encoding="utf-8")
    )
    assert registry["counts"] == {"matched": 1, "unmatched": 1}
    assert [row["source_product_id"] for row in gaps] == ["2"]
