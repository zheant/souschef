"""Capture hebdomadaire des rayons publics de Super C.

Le module ne connaît ni SQLAlchemy ni le solveur. Il sélectionne un magasin,
parcourt des chemins de catégories explicites et produit le JSON brut attendu
par :class:`SuperCCaptureAdapter`.
"""

from __future__ import annotations

import logging
import math
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import Message
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from typing import Callable, Iterable
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener


BASE_URL = "https://www.superc.ca"
DEALS_PATH = (
    "/recherche?sortOrder=relevance&"
    "filter=%3Arelevance%3Adeal%3AToutes+les+promotions"
)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36 "
    "Souschef/0.1"
)
_MONEY = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s*\$")
_UNIT_PRICE = re.compile(
    r"(?P<price>\d+(?:[.,]\d{1,2})?)\s*\$\s*/\s*"
    r"(?:(?P<quantity>\d+(?:[.,]\d+)?)\s*)?"
    r"(?P<unit>kg|g|mg|lb|lbs|oz|l|ml|unit(?:é|e)s?|un|ch|ea)\b",
    re.IGNORECASE,
)
_MULTIPACK = re.compile(
    r"(?P<count>\d+)\s*[x×]\s*(?P<qty>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>kg|g|mg|lb|lbs|oz|l|ml|unit(?:é|e)s?|un|ch|ea)\b",
    re.IGNORECASE,
)
_QUANTITY = re.compile(
    r"(?P<qty>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>kg|g|mg|lb|lbs|oz|l|ml|unit(?:é|e)s?|un|ch|ea)\b",
    re.IGNORECASE,
)
_UNIT_ALIASES = {
    "un": "ea",
    "ch": "ea",
    "unit": "ea",
    "unite": "ea",
    "unites": "ea",
    "unité": "ea",
    "unités": "ea",
}
_MASS_VOLUME_UNITS = {"kg", "g", "mg", "lb", "lbs", "oz", "l", "ml"}
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
logger = logging.getLogger(__name__)


@dataclass
class _HttpIdentity:
    opener: object
    store_selected: bool = False


@dataclass
class _ProductBuilder:
    attrs: dict[str, str]
    div_depth: int = 1
    elements: list[tuple[str, str | None]] = field(
        default_factory=lambda: [("div", None)]
    )
    text: dict[str, list[str]] = field(
        default_factory=lambda: {
            "brand": [],
            "package": [],
            "regular": [],
            "unit_price": [],
        }
    )
    all_text: list[str] = field(default_factory=list)
    product_path: str | None = None
    main_price: str | None = None
    price_variant: str | None = None
    promo: bool = False

    def start(self, tag: str, attrs: dict[str, str]) -> None:
        if tag == "div":
            self.div_depth += 1
        classes = set(attrs.get("class", "").split())
        capture = None
        if "head__brand" in classes:
            capture = "brand"
        elif "head__unit-details" in classes:
            capture = "package"
        elif "pricing__before-price" in classes:
            capture = "regular"
        elif "pricing__secondary-price" in classes:
            capture = "unit_price"
        if "promo-price" in classes:
            self.promo = True
        if attrs.get("data-main-price"):
            self.main_price = attrs["data-main-price"]
            self.price_variant = attrs.get("data-variant-price") or None
        if tag == "a" and "product-details-link" in classes:
            self.product_path = self.product_path or attrs.get("href")
        self.elements.append((tag, capture))

    def data(self, value: str) -> None:
        value = " ".join(value.split())
        if not value:
            return
        self.all_text.append(value)
        for _tag, capture in reversed(self.elements):
            if capture:
                self.text[capture].append(value)
                break

    def end(self, tag: str) -> bool:
        for index in range(len(self.elements) - 1, -1, -1):
            if self.elements[index][0] == tag:
                del self.elements[index:]
                break
        if tag == "div":
            self.div_depth -= 1
        return self.div_depth == 0

    def as_product(self) -> dict:
        source_id = self.attrs.get("data-product-code", "").strip()
        name = self.attrs.get("data-product-name", "").strip()
        unit_details = " ".join(self.text["package"])
        weighted = self.attrs.get("data-is-weighted", "false").casefold() == "true"
        normalized_package = _normalize_package(unit_details)
        unit_price = _parse_unit_price(" ".join(self.text["unit_price"]))
        regular = _first_money(" ".join(self.text["regular"]))
        full_text = " ".join(self.all_text).casefold()
        inactive = self.attrs.get("data-is-inactive", "false").casefold() == "true"
        return {
            "retailer_product_id": source_id,
            "upc": source_id if source_id.isdigit() and len(source_id) >= 8 else None,
            "name": name,
            "brand": " ".join(self.text["brand"]).strip() or None,
            "package_text": None if weighted else normalized_package,
            "unit_details_text": unit_details or None,
            "sale_mode": "variable_weight" if weighted else "fixed_package",
            "average_package_text": (
                normalized_package
                if weighted and _describes_average_quantity(unit_details)
                else None
            ),
            "purchase_increment": self.attrs.get("data-unit-increment") or None,
            "price_variant_text": self.price_variant,
            "displayed_unit_price": unit_price[0] if unit_price else None,
            "unit_price_reference_quantity": unit_price[1] if unit_price else None,
            "unit_price_reference_unit": unit_price[2] if unit_price else None,
            "displayed_price": self.main_price,
            "displayed_regular_price": regular,
            "displayed_sale_price": self.main_price if self.promo else None,
            "is_promo": self.promo,
            "product_url": urljoin(BASE_URL, self.product_path or ""),
            "category_url": self.attrs.get("data-category-url"),
            "in_listing": not inactive and "rupture de stock" not in full_text,
        }


class SuperCPageParser(HTMLParser):
    """Lit les tuiles produit sans dépendance HTML externe."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.products: list[dict] = []
        self.total_results: int | None = None
        self.page_paths: set[str] = set()
        self._product: _ProductBuilder | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {key: value or "" for key, value in attrs}
        if self.total_results is None and values.get("data-total-results", "").isdigit():
            self.total_results = int(values["data-total-results"])
        if tag == "a" and "-page-" in values.get("href", ""):
            self.page_paths.add(values["href"])

        classes = set(values.get("class", "").split())
        if self._product is None:
            if tag == "div" and "default-product-tile" in classes:
                self._product = _ProductBuilder(values)
            return
        self._product.start(tag, values)

    def handle_data(self, data: str) -> None:
        if self._product is not None:
            self._product.data(data)

    def handle_endtag(self, tag: str) -> None:
        if self._product is None:
            return
        if self._product.end(tag):
            product = self._product.as_product()
            if product["retailer_product_id"]:
                self.products.append(product)
            self._product = None


class SuperCWebExtractor:
    """Client HTTP poli et rejouable pour les catégories Super C publiques."""

    def __init__(
        self,
        store_id: str,
        *,
        request_delay_seconds: float = 10,
        request_jitter_seconds: float = 0,
        retries: int = 5,
        timeout_seconds: float = 30,
        proxies: Iterable[str] | None = None,
        user_agent: str | None = None,
    ) -> None:
        if not str(store_id).isdigit():
            raise ValueError("Le store_id Super C doit être numérique.")
        if request_jitter_seconds < 0:
            raise ValueError("Le jitter Super C ne peut pas être négatif.")
        self.store_id = str(store_id)
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.request_jitter_seconds = request_jitter_seconds
        self.retries = max(0, retries)
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent or _USER_AGENT
        proxy_urls = [_normalize_proxy(value) for value in (proxies or [])]
        self._identities = [
            _HttpIdentity(
                build_opener(
                    *(
                        [ProxyHandler({"http": proxy, "https": proxy})]
                        if proxy is not None
                        else []
                    ),
                    HTTPCookieProcessor(CookieJar()),
                )
            )
            for proxy in (proxy_urls or [None])
        ]
        self._identity_index = 0
        self._last_request_at = 0.0

    def capture_category(
        self,
        category: str,
        *,
        max_pages: int | None = None,
        progress: Callable[[int, int, int, int], None] | None = None,
        page_captured: Callable[[int, dict], None] | None = None,
    ) -> list[dict]:
        path = normalize_category_path(category)
        return self._capture_listing(
            path,
            max_pages=max_pages,
            progress=progress,
            listing_kind="category",
            page_captured=page_captured,
        )

    def capture_deals(
        self,
        deals_path: str,
        *,
        max_pages: int | None = None,
        progress: Callable[[int, int, int, int], None] | None = None,
        page_captured: Callable[[int, dict], None] | None = None,
    ) -> list[dict]:
        """Capture la liste officielle « Toutes les promotions »."""
        path = normalize_deals_path(deals_path)
        return self._capture_listing(
            path,
            max_pages=max_pages,
            progress=progress,
            listing_kind="weekly_deals",
            page_captured=page_captured,
        )

    def _capture_listing(
        self,
        path: str,
        *,
        max_pages: int | None,
        progress: Callable[[int, int, int, int], None] | None,
        listing_kind: str,
        page_captured: Callable[[int, dict], None] | None,
    ) -> list[dict]:
        captures: list[dict] = []
        expected_pages: int | None = None
        page = 1
        seen: set[str] = set()

        while expected_pages is None or page <= expected_pages:
            if max_pages is not None and page > max_pages:
                break
            page_path = (
                _deals_page_path(path, page)
                if listing_kind == "weekly_deals"
                else _page_path(path, page)
            )
            url = urljoin(BASE_URL, page_path)
            html = self._request(url, requires_store=True)
            self._verify_store(html)
            parser = SuperCPageParser()
            parser.feed(html)
            products = [
                product
                for product in parser.products
                if product["retailer_product_id"] not in seen
            ]
            if not products:
                if expected_pages is None:
                    break
                if progress is not None:
                    progress(
                        page,
                        expected_pages,
                        len(seen),
                        parser.total_results or len(seen),
                    )
                page += 1
                continue
            seen.update(product["retailer_product_id"] for product in products)
            captured_at = datetime.now(timezone.utc).isoformat()
            payload = {
                "captured_at": captured_at,
                "retailer": "Super C",
                "store_id": self.store_id,
                "category": path,
                "listing_kind": listing_kind,
                "source_url": url,
                "products": products,
            }
            captures.append(payload)
            if page_captured is not None:
                page_captured(page, payload)
            if expected_pages is None:
                expected_pages = _expected_page_count(parser, listing_kind)
            if progress is not None:
                progress(
                    page,
                    expected_pages,
                    len(seen),
                    parser.total_results or len(seen),
                )
            page += 1
        return captures

    def _select_store(self, identity: _HttpIdentity) -> None:
        if identity.store_selected:
            return
        self._open(identity, Request(urljoin(BASE_URL, "/"), headers=self._headers()))
        body = urlencode({"userConfirmation": "true", "lang": "fr"}).encode()
        request = Request(
            urljoin(BASE_URL, f"/stores/my-store/{self.store_id}"),
            data=body,
            headers=self._headers(
                {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": urljoin(BASE_URL, "/"),
                }
            ),
            method="POST",
        )
        self._open(identity, request)
        identity.store_selected = True

    def _verify_store(self, html: str) -> None:
        match = re.search(r"var\s+userStoreId\s*=\s*(\d+)\s*;", html)
        if match is None or match.group(1) != self.store_id:
            actual = match.group(1) if match else "introuvable"
            raise RuntimeError(
                f"Super C n'a pas conservé le magasin {self.store_id}; magasin lu: {actual}."
            )

    def _request(
        self,
        url: str,
        *,
        data: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
        requires_store: bool = False,
    ) -> str:
        headers = self._headers(extra_headers)
        for attempt in range(self.retries + 1):
            identity = self._identities[self._identity_index]
            request = Request(
                url,
                data=data,
                headers=headers,
                method="POST" if data else "GET",
            )
            try:
                if requires_store:
                    self._select_store(identity)
                return self._open(identity, request)
            except HTTPError as error:
                if error.code not in _RETRYABLE_STATUS_CODES or attempt == self.retries:
                    raise RuntimeError(
                        f"Super C a répondu HTTP {error.code} pour {url}"
                    ) from error
                retry_after = _retry_after_seconds(
                    error.headers.get("Retry-After") if error.headers else None
                )
                if retry_after is not None:
                    wait = retry_after
                elif error.code == 429:
                    wait = 30 * (attempt + 1)
                else:
                    wait = 2 ** attempt
                reason = f"HTTP {error.code}"
            except URLError as error:
                if attempt == self.retries:
                    raise RuntimeError(
                        f"Super C est inaccessible pour {url}: {error.reason}"
                    ) from error
                wait = 2 ** attempt
                reason = f"réseau: {error.reason}"

            self._rotate_identity()
            logger.warning(
                "Nouvelle tentative Super C après %s (tentative %d/%d, identité %d/%d)",
                reason,
                attempt + 2,
                self.retries + 1,
                self._identity_index + 1,
                len(self._identities),
            )
            time.sleep(max(self.request_delay_seconds, wait))
        raise AssertionError("Boucle de tentatives Super C épuisée sans résultat.")

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Language": "fr-CA,fr;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        }
        headers.update(extra or {})
        return headers

    def _open(self, identity: _HttpIdentity, request: Request) -> str:
        elapsed = time.monotonic() - self._last_request_at
        delay = self.request_delay_seconds
        if self.request_jitter_seconds:
            delay += random.uniform(0, self.request_jitter_seconds)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        try:
            with identity.opener.open(request, timeout=self.timeout_seconds) as response:
                return _decode(response.read(), response.headers)
        finally:
            self._last_request_at = time.monotonic()

    def _rotate_identity(self) -> None:
        self._identity_index = (self._identity_index + 1) % len(self._identities)


def normalize_category_path(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.netloc and parsed.netloc.casefold() not in {"www.superc.ca", "superc.ca"}:
        raise ValueError(f"Domaine de catégorie Super C invalide: {parsed.netloc!r}")
    path = parsed.path.rstrip("/")
    if not path.startswith("/allees/"):
        path = "/allees/" + path.lstrip("/")
    if parsed.query or parsed.fragment or not re.fullmatch(r"/allees/[a-z0-9/-]+", path):
        raise ValueError(f"Catégorie Super C invalide: {value!r}")
    if re.search(r"-page-\d+$", path):
        raise ValueError("Configurer la catégorie de base, sans suffixe -page-N.")
    return path


def normalize_deals_path(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.netloc and parsed.netloc.casefold() not in {
        "www.superc.ca",
        "superc.ca",
    }:
        raise ValueError(f"Domaine de rabais Super C invalide: {parsed.netloc!r}")
    expected_query = {
        "sortOrder": "relevance",
        "filter": ":relevance:deal:Toutes les promotions",
    }
    if (
        parsed.path.rstrip("/") != "/recherche"
        or parsed.fragment
        or dict(parse_qsl(parsed.query)) != expected_query
    ):
        raise ValueError(f"URL de rabais Super C invalide: {value!r}")
    return DEALS_PATH


def _page_path(category_path: str, page: int) -> str:
    return category_path if page == 1 else f"{category_path}-page-{page}"


def _deals_page_path(deals_path: str, page: int) -> str:
    if page == 1:
        return deals_path
    parsed = urlsplit(deals_path)
    return urlunsplit(("", "", f"{parsed.path}-page-{page}", parsed.query, ""))


def _expected_page_count(parser: SuperCPageParser, listing_kind: str) -> int:
    if listing_kind == "weekly_deals":
        linked_pages = [
            int(match.group(1))
            for path in parser.page_paths
            if (match := re.search(r"-page-(\d+)(?:\?|$)", path))
        ]
        if linked_pages:
            return max(linked_pages)
    total = parser.total_results or len(parser.products)
    return max(1, math.ceil(total / len(parser.products)))


def _first_money(value: str) -> str | None:
    match = _MONEY.search(value)
    return match.group(1).replace(",", ".") if match else None


def _parse_unit_price(value: str) -> tuple[str, str, str] | None:
    """Retourne le premier prix unitaire affiché, sans conversion implicite.

    Super C affiche généralement le prix métrique avant l'équivalent impérial.
    La capture conserve donc la quantité et l'unité de référence telles que
    publiées; l'adaptateur décidera ensuite si elles sont compatibles avec
    l'ingrédient canonique.
    """
    match = _UNIT_PRICE.search(" ".join(value.split()))
    if match is None:
        return None
    return (
        match.group("price").replace(",", "."),
        (match.group("quantity") or "1").replace(",", "."),
        _normalize_unit(match.group("unit")),
    )


def _describes_average_quantity(value: str) -> bool:
    normalized = value.casefold()
    return "moyenne" in normalized or "environ" in normalized or "average" in normalized


def _normalize_package(value: str) -> str | None:
    value = " ".join(value.split())
    if not value:
        return None
    multipack = _MULTIPACK.search(value)
    if multipack:
        unit = _normalize_unit(multipack.group("unit"))
        return (
            f"{multipack.group('count')} x "
            f"{multipack.group('qty').replace(',', '.')} {unit}"
        )
    matches = list(_QUANTITY.finditer(value))
    if not matches:
        return None
    preferred = next(
        (
            match
            for match in reversed(matches)
            if _normalize_unit(match.group("unit")) in _MASS_VOLUME_UNITS
        ),
        matches[-1],
    )
    return (
        f"{preferred.group('qty').replace(',', '.')} "
        f"{_normalize_unit(preferred.group('unit'))}"
    )


def _normalize_unit(value: str) -> str:
    return _UNIT_ALIASES.get(value.casefold(), value.casefold())


def _normalize_proxy(value: str) -> str:
    proxy = str(value).strip()
    if not proxy:
        raise ValueError("Une adresse de proxy Super C ne peut pas être vide.")
    if "://" not in proxy:
        proxy = f"http://{proxy}"
    parsed = urlsplit(proxy)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(
            "Les proxys Super C doivent utiliser une URL HTTP ou HTTPS valide."
        )
    return proxy


def _retry_after_seconds(
    value: str | None, *, now: datetime | None = None
) -> float | None:
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        target = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return max(0.0, (target - current).total_seconds())


def _decode(payload: bytes, headers: Message) -> str:
    charset = headers.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")
