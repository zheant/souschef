"""Capture navigateur des pages publiques du catalogue Maxi.

Maxi refuse actuellement les navigateurs sans interface. Ce collecteur utilise
donc un profil Edge distinct et visible. Il ne contourne pas les contrôles du
site : si Maxi demande une vérification, la fenêtre reste disponible pour que
l'utilisateur puisse la compléter avant la nouvelle tentative.
"""

from __future__ import annotations

import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


BASE_URL = "https://www.maxi.ca"
_MAXI_HOSTS = {"maxi.ca", "www.maxi.ca"}
_MAXI_DEALS_PATHS = {"/fr/collection/deals-centre-value"}
_MONEY = re.compile(r"(\d+(?:[.,]\d{1,2})?)")
_RETRYABLE_STATUS_CODES = {403, 408, 425, 429, 500, 502, 503, 504}


class MaxiBrowserExtractor:
    """Collecteur paginé, ralenti et reprenable des tuiles produit Maxi."""

    def __init__(
        self,
        store_id: str,
        *,
        profile_dir: str | Path,
        browser_channel: str = "msedge",
        headless: bool = False,
        request_delay_seconds: float = 4,
        request_jitter_seconds: float = 1,
        retries: int = 3,
        timeout_seconds: float = 60,
        manual_intervention_timeout_seconds: float = 120,
        diagnostic_dir: str | Path | None = None,
    ) -> None:
        if not str(store_id).isdigit():
            raise ValueError("Le store_id Maxi doit être numérique.")
        if request_jitter_seconds < 0:
            raise ValueError("Le jitter Maxi ne peut pas être négatif.")
        self.store_id = str(store_id)
        self.profile_dir = Path(profile_dir).resolve()
        self.browser_channel = browser_channel
        self.headless = headless
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.request_jitter_seconds = request_jitter_seconds
        self.retries = max(0, retries)
        self.timeout_ms = max(1, int(timeout_seconds * 1000))
        self.manual_intervention_timeout_seconds = max(
            0.0, manual_intervention_timeout_seconds
        )
        self.diagnostic_dir = (
            Path(diagnostic_dir).resolve() if diagnostic_dir is not None else None
        )

    def capture_category(
        self,
        category_url: str,
        *,
        max_pages: int | None = None,
        progress: Callable[[int, int, int], None] | None = None,
        page_captured: Callable[[int, dict], None] | None = None,
    ) -> list[dict]:
        """Capture une catégorie jusqu'à ce qu'une page n'ajoute aucun produit."""
        base_url = normalize_category_url(category_url)
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages Maxi doit être positif.")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:  # pragma: no cover - message d'installation
            raise RuntimeError(
                "Playwright manque. Réinstallez le projet avec `pip install -e backend`."
            ) from error

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        captures: list[dict] = []
        seen: set[str] = set()
        last_request_at = 0.0

        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(self.profile_dir),
                channel=self.browser_channel,
                headless=self.headless,
                locale="fr-CA",
                timezone_id="America/Toronto",
                viewport={"width": 1440, "height": 1000},
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                page_number = 1
                while max_pages is None or page_number <= max_pages:
                    elapsed = time.monotonic() - last_request_at
                    delay = self.request_delay_seconds + random.uniform(
                        0, self.request_jitter_seconds
                    )
                    if elapsed < delay:
                        time.sleep(delay - elapsed)

                    url = _page_url(base_url, page_number)
                    self._open_product_page(page, url)
                    last_request_at = time.monotonic()
                    self._verify_store(context)
                    snapshots = page.locator(
                        '[data-testid="product-grid-component"]'
                    ).evaluate_all(_PRODUCT_SNAPSHOT_SCRIPT)
                    products = []
                    for snapshot in snapshots:
                        product = product_from_snapshot(snapshot, category_url=url)
                        source_id = product["retailer_product_id"]
                        if source_id and source_id not in seen:
                            products.append(product)
                            seen.add(source_id)
                    if not products:
                        break

                    payload = {
                        "captured_at": datetime.now(timezone.utc).isoformat(),
                        "retailer": "Maxi",
                        "store_id": self.store_id,
                        "category": base_url,
                        "source_url": url,
                        "products": products,
                    }
                    captures.append(payload)
                    if page_captured is not None:
                        page_captured(page_number, payload)
                    if progress is not None:
                        progress(page_number, len(products), len(seen))
                    page_number += 1
            except Exception:
                self._save_diagnostic(page)
                raise
            finally:
                context.close()
        return captures

    def _open_product_page(self, page, url: str) -> None:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = page.goto(
                    url, wait_until="domcontentloaded", timeout=self.timeout_ms
                )
                status = response.status if response is not None else 0
                if status in _RETRYABLE_STATUS_CODES:
                    raise RuntimeError(f"HTTP {status}")
                if status >= 400:
                    raise RuntimeError(f"HTTP {status}")
                try:
                    page.wait_for_load_state(
                        "load", timeout=min(self.timeout_ms, 15_000)
                    )
                except Exception:
                    # Le catalogue utile est rendu côté serveur; les balises
                    # analytiques peuvent continuer après que les tuiles soient prêtes.
                    pass
                raw_title = page.title().strip()
                raw_body = page.locator("body").inner_text(timeout=self.timeout_ms).strip()
                title = raw_title.casefold()
                body = raw_body.casefold()
                if "access denied" in title or "access denied" in body[:500]:
                    raise RuntimeError("HTTP 403 (Access Denied)")
                if not raw_title or len(raw_body) < 100:
                    raise RuntimeError(
                        "Access Denied probable (réponse Maxi vide ou incomplète)"
                    )
                try:
                    page.wait_for_function(
                        """selector => document.querySelectorAll(selector).length > 1""",
                        '[data-testid="product-grid-component"] '
                        '[data-testid="product-title"]',
                        timeout=min(self.timeout_ms, 15_000),
                    )
                except Exception:
                    # Une dernière page peut légitimement ne contenir qu'une tuile.
                    pass
                return
            except Exception as error:
                last_error = error
                if attempt == self.retries:
                    break
                wait = min(30.0, 2.0 ** attempt)
                if "access denied" in str(error).casefold() and not self.headless:
                    wait = max(wait, self.manual_intervention_timeout_seconds)
                    print(
                        "[Maxi] Vérification demandée. Complétez-la dans la "
                        f"fenêtre Edge; reprise dans {wait:.0f} s.",
                        flush=True,
                    )
                time.sleep(wait)
        raise RuntimeError(
            f"Maxi n'a pas fourni une page produit exploitable pour {url}: {last_error}"
        ) from last_error

    def _verify_store(self, context) -> None:
        cookies = context.cookies(BASE_URL)
        actual = next(
            (
                str(cookie["value"])
                for cookie in cookies
                if cookie.get("name") == "auto_store_selected"
            ),
            None,
        )
        if actual != self.store_id:
            shown = actual or "introuvable"
            raise RuntimeError(
                f"Maxi a sélectionné le magasin {shown}, mais {self.store_id} est requis. "
                "Choisissez le bon magasin dans la fenêtre Edge puis relancez."
            )

    def _save_diagnostic(self, page) -> None:
        if self.diagnostic_dir is None:
            return
        self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        try:
            page.screenshot(
                path=str(self.diagnostic_dir / f"maxi-{stamp}.png"), full_page=True
            )
        except Exception:
            pass


def normalize_category_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.netloc.casefold() not in _MAXI_HOSTS
    ):
        raise ValueError(f"URL de catégorie Maxi invalide: {value!r}")
    path = parsed.path.rstrip("/")
    if ("/c/" not in path and path not in _MAXI_DEALS_PATHS) or parsed.fragment:
        raise ValueError(f"URL de catégorie Maxi invalide: {value!r}")
    return urlunsplit(("https", "www.maxi.ca", path, "", ""))


def product_from_snapshot(snapshot: dict, *, category_url: str) -> dict:
    source_id = str(snapshot.get("id") or "").strip()
    name = " ".join(str(snapshot.get("name") or "").split())
    href = str(snapshot.get("href") or "").strip()
    regular = _money(snapshot.get("regular_price"))
    sale = _money(snapshot.get("sale_price"))
    displayed = sale or regular
    card_text = str(snapshot.get("card_text") or "").casefold()
    return {
        "retailer_product_id": source_id,
        "upc": None,
        "name": name,
        "brand": _optional_text(snapshot.get("brand")),
        "package_text": _optional_text(snapshot.get("package_text")),
        "displayed_price": displayed,
        "displayed_regular_price": regular,
        "displayed_sale_price": sale,
        "is_promo": sale is not None,
        "product_url": _absolute_product_url(href),
        "category_url": category_url,
        "in_listing": not any(
            marker in card_text
            for marker in ("rupture de stock", "out of stock", "non disponible")
        ),
    }


def _page_url(category_url: str, page: int) -> str:
    parsed = urlsplit(category_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["page"] = str(page)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def _money(value: object) -> str | None:
    match = _MONEY.search(str(value or "").replace("\u00a0", " "))
    if match is None:
        return None
    return match.group(1).replace(",", ".")


def _optional_text(value: object) -> str | None:
    text = " ".join(str(value or "").replace("\u00a0", " ").split())
    return text or None


def _absolute_product_url(href: str) -> str:
    if not href:
        return ""
    parsed = urlsplit(href)
    path = parsed.path
    return urlunsplit(("https", "www.maxi.ca", path, "", ""))


_PRODUCT_SNAPSHOT_SCRIPT = """
grids => {
 const titleSelector = '[data-testid="product-title"]';
 const hasMultiProductGrid = grids.some(grid => grid.querySelectorAll(titleSelector).length > 1);
 const titles = grids.flatMap(grid => {
   const found = [...grid.querySelectorAll(titleSelector)];
   return hasMultiProductGrid && found.length === 1 ? [] : found;
 });
 return titles.map(title => {
  const card = title.closest('.chakra-linkbox');
  const anchor = title.closest('a[href*="/p/"]') || card?.querySelector('a[href*="/p/"]');
  const text = selector => card?.querySelector(selector)?.textContent?.trim() || '';
  return {
    id: title.id || '',
    name: title.textContent?.trim() || '',
    href: anchor?.getAttribute('href') || '',
    brand: text('[data-testid="product-brand"]'),
    package_text: text('[data-testid="product-package-size"]'),
    regular_price: text('[data-testid="regular-price"]') || text('[data-testid="was-price"]'),
    sale_price: text('[data-testid="sale-price"]'),
    card_text: card?.textContent || ''
  };
 });
}
"""
