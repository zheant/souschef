"""Capturer Maxi et Super C en parallèle, puis importer la même semaine.

Chaque collecte écrit dans un dossier d'exécution isolé. Sans ``--apply``, le
script capture et produit les rapports, mais ne modifie pas PostgreSQL.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

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
from app.adapters.maxi_web import MaxiBrowserExtractor, normalize_category_url
from app.adapters.superc_capture import SuperCCaptureAdapter
from app.adapters.superc_web import (
    SuperCWebExtractor,
    normalize_category_path,
    normalize_deals_path,
)
from app.ingestion.product_registry import (
    canonical_gap_candidates,
    update_product_registry,
)


@dataclass(frozen=True)
class CircularPeriod:
    week: str
    valid_from: date
    valid_to: date


@dataclass(frozen=True)
class CaptureResult:
    capture_dirs: tuple[Path, ...]
    categories: tuple[str, ...]
    pages_captured: int
    rows_captured_before_deduplication: int
    fresh: bool
    complete_catalogue: bool
    deal_targets: tuple[str, ...] = ()
    deal_products_captured: int = 0
    deal_promotions_captured: int = 0
    distinct_products_captured: int = 0


def circular_period(on_date: date) -> CircularPeriod:
    """Période d'épicerie québécoise jeudi-mercredi contenant ``on_date``."""
    thursday = on_date - timedelta(days=(on_date.weekday() - 3) % 7)
    iso = thursday.isocalendar()
    return CircularPeriod(
        week=f"{iso.year}-W{iso.week:02d}",
        valid_from=thursday,
        valid_to=thursday + timedelta(days=6),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "catalogues.json")
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--skip-maxi", action="store_true")
    parser.add_argument("--skip-superc", action="store_true")
    parser.add_argument(
        "--maxi-category",
        action="append",
        help="Remplace temporairement les catégories Maxi configurées.",
    )
    parser.add_argument(
        "--superc-category",
        action="append",
        help="Remplace temporairement les catégories Super C configurées.",
    )
    parser.add_argument(
        "--reuse-maxi-captures",
        action="store_true",
        help="Rejoue la dernière capture Maxi complète de la semaine.",
    )
    parser.add_argument(
        "--reuse-superc-captures",
        action="store_true",
        help="Rejoue la dernière capture Super C complète de la semaine.",
    )
    parser.add_argument(
        "--maxi-max-pages", type=int, help="Limite de diagnostic Maxi."
    )
    parser.add_argument(
        "--max-pages", type=int, help="Limite de diagnostic Super C par catégorie."
    )
    parser.add_argument(
        "--report-suffix",
        help="Suffixe optionnel pour conserver un rapport complémentaire.",
    )
    args = parser.parse_args()

    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    period = circular_period(args.date)
    output_root = _resolve_path(
        config_path, config.get("capture_root", "../data/catalogue-captures")
    )
    report_root = _resolve_path(
        config_path, config.get("report_root", "../data/catalogue-reports")
    )
    registry_root = _resolve_path(
        config_path, config.get("registry_root", "../data/catalogue-registry")
    )
    seed_dir = _resolve_path(config_path, config.get("seed_dir", "../seed/main"))
    recipe_ingredient_ids = _recipe_ingredient_ids(seed_dir)
    canonical_ingredient_ids = _canonical_ingredient_ids(seed_dir)
    product_conversions = load_product_conversions(
        _optional_path(config_path, config.get("procurement_rules"))
    )
    # Ces deux-là manquaient, et c'est le seul chemin qui écrit en base : les
    # gardes d'identité (produit composé, format de gros, rayon réservé) et le
    # barème de taxes ne s'appliquaient qu'au rapport hors ligne. Le catalogue
    # persisté et les devis publiés étaient donc calculés sous deux régimes
    # différents — la bière au miel restait appariée au miel dans `market`.
    identity_rules = load_identity_rules(
        _optional_path(config_path, config.get("identity_rules"))
    )
    tax_schedule = load_tax_schedule(
        _optional_path(config_path, config.get("tax_rates"))
    )
    run_id = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")

    maxi_config = config.get("maxi", {})
    superc_config = config.get("superc", {})
    jobs: dict[str, Callable[[], CaptureResult]] = {}
    if maxi_config.get("enabled", True) and not args.skip_maxi:
        jobs["maxi"] = lambda: _capture_maxi(
            config_path=config_path,
            config=maxi_config,
            output_root=output_root,
            report_root=report_root,
            period=period,
            run_id=run_id,
            reuse=args.reuse_maxi_captures,
            max_pages=args.maxi_max_pages,
            category_overrides=args.maxi_category,
        )
    if superc_config.get("enabled", True) and not args.skip_superc:
        jobs["superc"] = lambda: _capture_superc(
            config=superc_config,
            output_root=output_root,
            period=period,
            run_id=run_id,
            reuse=args.reuse_superc_captures,
            category_overrides=args.superc_category,
            max_pages=args.max_pages,
        )
    if not jobs:
        raise ValueError("Aucune bannière n'est activée.")

    print(
        "[Démarrage] " + " et ".join(name.title() for name in jobs) + " en parallèle",
        flush=True,
    )
    captures = _run_capture_jobs(jobs)

    adapters = []
    reports: dict[str, object] = {
        "week": period.week,
        "valid_from": period.valid_from.isoformat(),
        "valid_to": period.valid_to.isoformat(),
        "database_applied": args.apply,
        "run_id": run_id,
    }

    if "maxi" in captures:
        result = captures["maxi"]
        _validate_current_captures(list(result.capture_dirs), period, "Maxi")
        maxi = MaxiCaptureAdapter(
            result.capture_dirs,
            seed_dir,
            store_external_key=maxi_config["store_external_key"],
            week=period.week,
            valid_from=period.valid_from,
            valid_to=period.valid_to,
            overrides=load_match_overrides(
                _optional_path(config_path, maxi_config.get("overrides"))
            ),
            title_overrides=load_title_overrides(
                _optional_path(config_path, maxi_config.get("title_overrides"))
            ),
            product_conversions=product_conversions,
            identity_rules=identity_rules,
            tax_schedule=tax_schedule,
        )
        adapters.append(maxi)
        reports["maxi"] = _source_report(
            maxi,
            result,
            canonical_ingredient_ids,
            recipe_ingredient_ids,
        )
        if result.complete_catalogue:
            reports["maxi"].update(  # type: ignore[union-attr]
                _write_registry_files(maxi, registry_root, period.week)
            )
            reports["maxi"]["registry_updated"] = True  # type: ignore[index]
        else:
            reports["maxi"]["registry_updated"] = False  # type: ignore[index]
        _print_matching_summary("Maxi", reports["maxi"])  # type: ignore[arg-type]

    if "superc" in captures:
        result = captures["superc"]
        _validate_current_captures(list(result.capture_dirs), period, "Super C")
        superc = SuperCCaptureAdapter(
            result.capture_dirs,
            seed_dir,
            store_external_key=superc_config["store_external_key"],
            week=period.week,
            valid_from=period.valid_from,
            valid_to=period.valid_to,
            overrides=load_match_overrides(
                _optional_path(config_path, superc_config.get("overrides"))
            ),
            product_conversions=product_conversions,
            identity_rules=identity_rules,
            tax_schedule=tax_schedule,
        )
        adapters.append(superc)
        reports["superc"] = _source_report(
            superc,
            result,
            canonical_ingredient_ids,
            recipe_ingredient_ids,
        )
        if result.complete_catalogue:
            reports["superc"].update(  # type: ignore[union-attr]
                _write_registry_files(superc, registry_root, period.week)
            )
            reports["superc"]["registry_updated"] = True  # type: ignore[index]
        else:
            reports["superc"]["registry_updated"] = False  # type: ignore[index]
        _print_matching_summary("Super C", reports["superc"])  # type: ignore[arg-type]

    if args.apply:
        from app.db import SessionLocal
        from app.ingestion.retailer_catalogue import import_retailer_catalogue

        with SessionLocal.begin() as session:
            for adapter in adapters:
                reports[adapter.source_prefix]["database"] = import_retailer_catalogue(  # type: ignore[index]
                    session, adapter
                )

    report_root.mkdir(parents=True, exist_ok=True)
    report_suffix = ""
    if args.report_suffix:
        safe_suffix = re.sub(
            r"[^a-zA-Z0-9_-]+", "-", args.report_suffix
        ).strip("-")
        if not safe_suffix:
            raise ValueError("Le suffixe du rapport ne contient aucun caractère valide.")
        report_suffix = f"-{safe_suffix}"
    report_path = report_root / f"catalogues-{period.week}{report_suffix}.json"
    _write_json_atomic(report_path, reports)
    print(f"[Terminé] Rapport complet : {report_path}", flush=True)
    return 0


def _run_capture_jobs(
    jobs: dict[str, Callable[[], CaptureResult]],
) -> dict[str, CaptureResult]:
    """Démarre toutes les sources avant d'attendre leur résultat."""
    results: dict[str, CaptureResult] = {}
    failures: list[tuple[str, BaseException]] = []
    with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="catalogue") as pool:
        future_names = {pool.submit(job): name for name, job in jobs.items()}
        for future in as_completed(future_names):
            name = future_names[future]
            try:
                results[name] = future.result()
            except BaseException as error:
                failures.append((name, error))
    if failures:
        details = "; ".join(f"{name}: {error}" for name, error in failures)
        raise RuntimeError(f"Capture incomplète — {details}") from failures[0][1]
    return results


def _capture_maxi(
    *,
    config_path: Path,
    config: dict,
    output_root: Path,
    report_root: Path,
    period: CircularPeriod,
    run_id: str,
    reuse: bool,
    max_pages: int | None,
    category_overrides: list[str] | None,
) -> CaptureResult:
    weekly_root = output_root / "maxi" / period.week
    if reuse:
        result = _reuse_capture(weekly_root, "Maxi")
        print(f"[Maxi] {result.pages_captured} pages locales rejouées", flush=True)
        return result

    configured_categories = category_overrides or config.get("category_urls", [])
    categories = tuple(
        normalize_category_url(value) for value in configured_categories
    )
    if not categories:
        raise ValueError("Maxi exige au moins une category_urls dans la configuration.")
    deal_targets = (
        ()
        if category_overrides is not None
        else tuple(
            normalize_category_url(value) for value in config.get("deal_urls", [])
        )
    )
    if category_overrides is None and not deal_targets:
        raise ValueError(
            "Maxi exige au moins une deal_urls pour les rabais hebdomadaires."
        )
    targets = categories + deal_targets
    run_root = weekly_root / run_id
    profile_dir = _resolve_path(
        config_path, config.get("browser_profile", "../data/browser-profiles/maxi")
    )
    extractor = MaxiBrowserExtractor(
        str(config["store_id"]),
        profile_dir=profile_dir,
        browser_channel=str(config.get("browser_channel", "msedge")),
        headless=bool(config.get("headless", False)),
        request_delay_seconds=float(config.get("request_delay_seconds", 4)),
        request_jitter_seconds=float(config.get("request_jitter_seconds", 1)),
        retries=int(config.get("retries", 3)),
        timeout_seconds=float(config.get("timeout_seconds", 60)),
        manual_intervention_timeout_seconds=float(
            config.get("manual_intervention_timeout_seconds", 120)
        ),
        diagnostic_dir=report_root / "diagnostics",
    )
    capture_dirs: list[Path] = []
    page_count = 0
    source_count = 0
    deal_product_count = 0
    deal_promotion_count = 0
    distinct_product_ids: set[str] = set()
    reached_safety_limit = False
    configured_max_pages = config.get("max_pages")
    effective_max_pages = (
        int(max_pages if max_pages is not None else configured_max_pages)
        if max_pages is not None or configured_max_pages is not None
        else None
    )
    print(
        f"[Maxi] Magasin {config['store_id']} — {len(categories)} rayon(s), "
        f"{len(deal_targets)} cible(s) rabais",
        flush=True,
    )
    for category_index, category in enumerate(targets, start=1):
        directory = run_root / _maxi_category_slug(category)
        directory.mkdir(parents=True, exist_ok=True)
        capture_dirs.append(directory)

        def save_page(page_number: int, payload: dict) -> None:
            nonlocal page_count, source_count
            _write_json_atomic(directory / f"page-{page_number:03d}.json", payload)
            page_count += 1
            source_count += len(payload["products"])
            distinct_product_ids.update(
                str(product.get("retailer_product_id") or product.get("upc") or "")
                for product in payload["products"]
            )

        def show_progress(page: int, captured: int, total: int) -> None:
            print(
                f"[Maxi {category_index:02d}/{len(targets):02d}] "
                f"page {page} — {captured} nouveaux, {total} uniques",
                flush=True,
            )

        pages = extractor.capture_category(
            category,
            max_pages=effective_max_pages,
            progress=show_progress,
            page_captured=save_page,
        )
        if category in deal_targets:
            products, promotions = _deal_capture_counts("Maxi", pages)
            deal_product_count += products
            deal_promotion_count += promotions
        if effective_max_pages is not None and len(pages) >= effective_max_pages:
            reached_safety_limit = True
    if page_count == 0:
        raise RuntimeError("Maxi n'a retourné aucun produit.")
    complete_catalogue = (
        category_overrides is None
        and max_pages is None
        and not reached_safety_limit
    )
    _validate_capture_scale(
        "Maxi", len(distinct_product_ids - {""}), config, complete_catalogue
    )
    _write_complete_manifest(
        run_root,
        targets,
        page_count,
        source_count,
        complete_catalogue,
        deal_targets,
        deal_product_count,
        deal_promotion_count,
        len(distinct_product_ids - {""}),
    )
    return CaptureResult(
        tuple(capture_dirs), targets, page_count, source_count, True,
        complete_catalogue, deal_targets, deal_product_count,
        deal_promotion_count, len(distinct_product_ids - {""}),
    )


def _capture_superc(
    *,
    config: dict,
    output_root: Path,
    period: CircularPeriod,
    run_id: str,
    reuse: bool,
    category_overrides: list[str] | None,
    max_pages: int | None,
) -> CaptureResult:
    weekly_root = output_root / "superc" / period.week
    if reuse:
        result = _reuse_capture(weekly_root, "Super C")
        print(f"[Super C] {result.pages_captured} pages locales rejouées", flush=True)
        return result

    configured = category_overrides or config["categories"]
    categories = tuple(normalize_category_path(value) for value in configured)
    deal_targets = (
        ()
        if category_overrides is not None
        else tuple(normalize_deals_path(value) for value in config.get("deal_paths", []))
    )
    if category_overrides is None and not deal_targets:
        raise ValueError(
            "Super C exige au moins une deal_paths pour les rabais hebdomadaires."
        )
    targets = tuple(("category", value) for value in categories) + tuple(
        ("weekly_deals", value) for value in deal_targets
    )
    run_root = weekly_root / run_id
    extractor = SuperCWebExtractor(
        str(config["store_id"]),
        request_delay_seconds=float(config.get("request_delay_seconds", 10)),
        request_jitter_seconds=float(config.get("request_jitter_seconds", 0)),
        retries=int(config.get("retries", 5)),
        timeout_seconds=float(config.get("timeout_seconds", 30)),
        proxies=_configured_proxies(config),
        user_agent=config.get("user_agent"),
    )
    capture_dirs: list[Path] = []
    page_count = 0
    source_count = 0
    deal_product_count = 0
    deal_promotion_count = 0
    distinct_product_ids: set[str] = set()
    print(
        f"[Super C] Magasin {config['store_id']} — {len(categories)} rayon(s), "
        f"{len(deal_targets)} cible(s) rabais",
        flush=True,
    )
    for category_index, (listing_kind, category) in enumerate(targets, start=1):
        label = (
            "rabais hebdomadaires"
            if listing_kind == "weekly_deals"
            else category.removeprefix("/allees/")
        )
        print(
            f"[Super C {category_index:02d}/{len(targets):02d}] {label}",
            flush=True,
        )

        def show_progress(page: int, total_pages: int, captured: int, total: int) -> None:
            print(
                f"  page {page}/{total_pages} — {captured}/{total} produits capturés",
                flush=True,
            )

        directory = run_root / _category_slug(category)
        directory.mkdir(parents=True, exist_ok=True)
        capture_dirs.append(directory)

        def save_page(page_number: int, payload: dict) -> None:
            nonlocal page_count, source_count
            _write_json_atomic(directory / f"page-{page_number:03d}.json", payload)
            page_count += 1
            source_count += len(payload["products"])
            distinct_product_ids.update(
                str(product.get("retailer_product_id") or product.get("upc") or "")
                for product in payload["products"]
            )

        capture = (
            extractor.capture_deals
            if listing_kind == "weekly_deals"
            else extractor.capture_category
        )
        pages = capture(
            category,
            max_pages=max_pages,
            progress=show_progress,
            page_captured=save_page,
        )
        if listing_kind == "weekly_deals":
            products, promotions = _deal_capture_counts("Super C", pages)
            deal_product_count += products
            deal_promotion_count += promotions
    if page_count == 0:
        raise RuntimeError("Super C n'a retourné aucun produit.")
    complete_catalogue = category_overrides is None and max_pages is None
    _validate_capture_scale(
        "Super C", len(distinct_product_ids - {""}), config, complete_catalogue
    )
    captured_targets = tuple(value for _kind, value in targets)
    _write_complete_manifest(
        run_root,
        captured_targets,
        page_count,
        source_count,
        complete_catalogue,
        deal_targets,
        deal_product_count,
        deal_promotion_count,
        len(distinct_product_ids - {""}),
    )
    return CaptureResult(
        tuple(capture_dirs), captured_targets, page_count, source_count, True,
        complete_catalogue, deal_targets, deal_product_count,
        deal_promotion_count, len(distinct_product_ids - {""}),
    )


def _reuse_capture(weekly_root: Path, source_name: str) -> CaptureResult:
    runs = sorted(
        (
            path
            for path in weekly_root.glob("run-*")
            if _is_reusable_capture(path)
        ),
        reverse=True,
    )
    if not runs:
        raise FileNotFoundError(
            f"Aucune exécution {source_name} complète dans {weekly_root}."
        )
    run_root = runs[0]
    manifest = json.loads((run_root / "_complete.json").read_text(encoding="utf-8"))
    capture_dirs = tuple(
        sorted(path for path in run_root.iterdir() if path.is_dir())
    )
    if not capture_dirs:
        raise FileNotFoundError(f"La capture {source_name} {run_root} est vide.")
    return CaptureResult(
        capture_dirs=capture_dirs,
        categories=tuple(manifest.get("categories", [])),
        pages_captured=int(manifest["pages_captured"]),
        rows_captured_before_deduplication=int(
            manifest["rows_captured_before_deduplication"]
        ),
        fresh=False,
        complete_catalogue=True,
        deal_targets=tuple(manifest.get("deal_targets", [])),
        deal_products_captured=int(manifest.get("deal_products_captured", 0)),
        deal_promotions_captured=int(manifest.get("deal_promotions_captured", 0)),
        distinct_products_captured=int(
            manifest.get("distinct_products_captured", 0)
        ),
    )


def _is_reusable_capture(run_root: Path) -> bool:
    manifest_path = run_root / "_complete.json"
    if not run_root.is_dir() or not manifest_path.exists():
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return bool(
        manifest.get("complete_catalogue")
        and manifest.get("deal_targets")
        and manifest.get("deal_promotions_captured", 0) > 0
    )


def _write_complete_manifest(
    run_root: Path,
    categories: tuple[str, ...],
    page_count: int,
    source_count: int,
    complete_catalogue: bool,
    deal_targets: tuple[str, ...] = (),
    deal_products_captured: int = 0,
    deal_promotions_captured: int = 0,
    distinct_products_captured: int = 0,
) -> None:
    _write_json_atomic(
        run_root / "_complete.json",
        {
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "categories": list(categories),
            "pages_captured": page_count,
            "rows_captured_before_deduplication": source_count,
            "complete_catalogue": complete_catalogue,
            "deal_targets": list(deal_targets),
            "deal_products_captured": deal_products_captured,
            "deal_promotions_captured": deal_promotions_captured,
            "distinct_products_captured": distinct_products_captured,
        },
    )


def _source_report(
    adapter,
    capture: CaptureResult,
    canonical_ingredient_ids: set[str],
    recipe_ingredient_ids: set[str],
) -> dict:
    return {
        **_adapter_report(adapter),
        "categories": list(capture.categories),
        "pages_captured": capture.pages_captured,
        "rows_captured_before_deduplication": (
            capture.rows_captured_before_deduplication
        ),
        "distinct_products_captured": capture.distinct_products_captured,
        "fresh_capture": capture.fresh,
        "complete_catalogue": capture.complete_catalogue,
        "weekly_deals_scanned": bool(capture.deal_targets),
        "deal_targets": list(capture.deal_targets),
        "deal_products_captured": capture.deal_products_captured,
        "deal_promotions_captured": capture.deal_promotions_captured,
        "canonical_catalogue_total": len(canonical_ingredient_ids),
        "recipe_ingredients_total": len(recipe_ingredient_ids),
        "recipe_ingredients_covered": len(
            _matched_canonical_ids(adapter) & recipe_ingredient_ids
        ),
    }


def _print_matching_summary(source_name: str, report: dict) -> None:
    counts = report["decision_counts"]
    print(
        f"[{source_name}] Rapprochement terminé — "
        f"{report['importable_products']} produits importables, "
        f"dont {report['promotional_products']} en rabais; "
        f"{report['recipe_ingredients_covered']}/{report['recipe_ingredients_total']} "
        f"ingrédients de recettes couverts; {counts.get('review', 0)} à réviser, "
        f"{counts.get('unmatched', 0)} sans ingrédient canonique, "
        f"{counts.get('rejected', 0)} exclus",
        flush=True,
    )
    if report["weekly_deals_scanned"]:
        print(
            f"[{source_name}] Rabais dédiés — "
            f"{report['deal_promotions_captured']}/"
            f"{report['deal_products_captured']} produits marqués en promotion",
            flush=True,
        )


def _deal_capture_counts(source_name: str, pages: list[dict]) -> tuple[int, int]:
    products = [product for page in pages for product in page["products"]]
    promotions = sum(bool(product.get("is_promo")) for product in products)
    if not products:
        raise RuntimeError(f"{source_name} n'a retourné aucun rabais hebdomadaire.")
    if promotions == 0:
        raise RuntimeError(
            f"{source_name} a retourné une page de rabais sans prix promotionnel."
        )
    return len(products), promotions


def _validate_capture_scale(
    source_name: str,
    distinct_products: int,
    config: dict,
    complete_catalogue: bool,
) -> None:
    if not complete_catalogue:
        return
    minimum = int(config.get("minimum_distinct_products", 1))
    if distinct_products < minimum:
        raise RuntimeError(
            f"Capture {source_name} anormalement petite: {distinct_products} "
            f"produits distincts, minimum configuré {minimum}."
        )


def _adapter_report(adapter) -> dict:
    return {
        **adapter.report(),
        "decisions": [decision.as_dict() for decision in adapter.decisions],
    }


def _matched_canonical_ids(adapter) -> set[str]:
    return {
        decision.canonical_ingredient_id
        for decision in adapter.decisions
        if decision.status == "matched" and decision.canonical_ingredient_id
    }


def _write_registry_files(adapter, registry_root: Path, week: str) -> dict[str, str]:
    registry_root.mkdir(parents=True, exist_ok=True)
    registry_path = registry_root / f"{adapter.source_prefix}.json"
    previous = (
        json.loads(registry_path.read_text(encoding="utf-8"))
        if registry_path.exists()
        else None
    )
    registry = update_product_registry(adapter, week=week, previous=previous)
    _write_json_atomic(registry_path, registry)
    gaps_path = registry_root / f"{adapter.source_prefix}-canonical-gaps.json"
    _write_json_atomic(gaps_path, canonical_gap_candidates(registry))
    return {
        "registry_path": str(registry_path),
        "canonical_gaps_path": str(gaps_path),
    }


def _validate_current_captures(
    directories: list[Path],
    period: CircularPeriod,
    source_name: str,
) -> None:
    timestamps = []
    for directory in directories:
        for path in directory.glob("*.json"):
            if path.name.startswith("_"):
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            value = payload.get("captured_at")
            if value:
                instant = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                timestamps.append(instant.date())
    if not timestamps:
        shown = ", ".join(str(path) for path in directories) or "aucun répertoire"
        raise FileNotFoundError(f"Aucune capture {source_name} trouvée dans: {shown}")
    outside = sorted(
        {value for value in timestamps if not period.valid_from <= value <= period.valid_to}
    )
    if outside:
        raise ValueError(
            f"Captures {source_name} hors de "
            f"{period.valid_from}..{period.valid_to}: {outside}"
        )


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _resolve_path(config_path: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def _optional_path(config_path: Path, value: str | None) -> Path | None:
    return _resolve_path(config_path, value) if value else None


def _configured_proxies(config: dict) -> list[str]:
    variable = str(config.get("proxy_environment_variable") or "").strip()
    if not variable:
        return []
    raw = os.environ.get(variable)
    if not raw:
        return []
    try:
        proxies = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{variable} doit contenir une liste JSON d'URL de proxy."
        ) from error
    if not isinstance(proxies, list) or not all(
        isinstance(value, str) and value.strip() for value in proxies
    ):
        raise ValueError(
            f"{variable} doit contenir une liste JSON d'URL de proxy non vides."
        )
    return proxies


def _category_slug(category: str) -> str:
    if category.startswith("/recherche?"):
        return "weekly-deals"
    return category.removeprefix("/allees/").replace("/", "__")


def _maxi_category_slug(category_url: str) -> str:
    match = re.search(r"/c/([^/?#]+)", category_url)
    if match:
        return f"category-{match.group(1)}"
    return "weekly-deals"


def _recipe_ingredient_ids(seed_dir: Path) -> set[str]:
    recipes = json.loads((seed_dir / "recipes.json").read_text(encoding="utf-8"))
    return {
        ingredient["canonical_ingredient_id"]
        for recipe in recipes
        for ingredient in recipe["ingredients"]
    }


def _canonical_ingredient_ids(seed_dir: Path) -> set[str]:
    ingredients = json.loads(
        (seed_dir / "canonical_ingredients.json").read_text(encoding="utf-8")
    )
    return {ingredient["id"] for ingredient in ingredients}


if __name__ == "__main__":
    raise SystemExit(main())
