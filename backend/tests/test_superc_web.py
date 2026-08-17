"""Extraction HTML publique de Super C, sans appel réseau dans la suite."""

from datetime import datetime, timezone
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError

from app.adapters.superc_web import (
    DEALS_PATH,
    SuperCCaptureIncomplete,
    SuperCPageParser,
    SuperCWebExtractor,
    _deals_page_path,
    _expected_page_count,
    _normalize_package,
    _retry_after_seconds,
    normalize_category_path,
    normalize_deals_path,
)


HTML = """
<div class="plpGridList" data-total-results="81">
  <div class="default-product-tile plp-tile" data-product-code="059749892582"
       data-product-name="Farine tout usage" data-is-weighted="false"
       data-is-inactive="false" data-category-url="/allees/garde-manger/farine">
    <a class="product-details-link" href="/farine/p/059749892582">
      <span class="head__brand">Selection</span>
      <span class="head__unit-details">2 x 2,5 kg</span>
    </a>
    <div class="content__pricing">
      <div class="pricing__before-price"><span>Prix régulier</span><span>9,99 $</span></div>
      <div data-main-price="7.49">
        <div class="pricing__sale-price promo-price"><span>7,49 $</span></div>
      </div>
    </div>
  </div>
  <div class="default-product-tile plp-tile" data-product-code="4011"
       data-product-name="Banane" data-is-weighted="true" data-is-inactive="false">
    <a class="product-details-link" href="/banane/p/4011">
      <span class="head__unit-details">1 un</span>
    </a>
    <div data-main-price="0.33"><span>0,33 $</span>
      <div class="pricing__secondary-price">
        <span>1,74 $ /<abbr title="Kilogram">kg</abbr></span>
        <span>0,79 $ /<abbr title="Pound">lb.</abbr></span>
      </div>
    </div>
    <span>En rupture de stock</span>
  </div>
</div>
<a href="/allees/fruits-page-2">2</a>
"""


def test_parser_preserves_identity_package_prices_and_promotion():
    parser = SuperCPageParser()
    parser.feed(HTML)

    assert parser.total_results == 81
    assert parser.page_paths == {"/allees/fruits-page-2"}
    assert len(parser.products) == 2
    flour = parser.products[0]
    assert flour == {
        "retailer_product_id": "059749892582",
        "upc": "059749892582",
        "name": "Farine tout usage",
            "brand": "Selection",
            "package_text": "2 x 2.5 kg",
            "unit_details_text": "2 x 2,5 kg",
            "sale_mode": "fixed_package",
            "average_package_text": None,
            "purchase_increment": None,
            "price_variant_text": None,
            "displayed_unit_price": None,
            "unit_price_reference_quantity": None,
            "unit_price_reference_unit": None,
        "displayed_price": "7.49",
        "displayed_regular_price": "9.99",
        "displayed_sale_price": "7.49",
        "is_promo": True,
        "product_url": "https://www.superc.ca/farine/p/059749892582",
        "category_url": "/allees/garde-manger/farine",
        "in_listing": True,
    }

    banana = parser.products[1]
    assert banana["package_text"] is None
    assert banana["sale_mode"] == "variable_weight"
    assert banana["average_package_text"] is None
    assert banana["purchase_increment"] is None
    assert banana["displayed_unit_price"] == "1.74"
    assert banana["unit_price_reference_quantity"] == "1"
    assert banana["unit_price_reference_unit"] == "kg"
    assert banana["in_listing"] is False


def test_parser_preserves_variable_weight_proof_without_faking_a_package():
    parser = SuperCPageParser()
    parser.feed(
        """
        <div class="default-product-tile" data-product-code="201021"
             data-product-name="Bœuf haché mi-maigre" data-is-weighted="true"
             data-unit-increment="450" data-is-inactive="false">
          <a class="product-details-link" href="/boeuf/p/201021">
            <span class="head__unit-details">
              Une barquette contient en moyenne 450 g
            </span>
          </a>
          <div data-main-price="8.42" data-variant-price="450g">
            <span class="price-update">8,42 $</span>
            <div class="pricing__secondary-price">
              <span>18,72 $ /<abbr title="Kilogram">kg</abbr></span>
              <span>8,49 $ /<abbr title="Pound">lb.</abbr></span>
            </div>
          </div>
        </div>
        """
    )

    product = parser.products[0]
    assert product["package_text"] is None
    assert product["sale_mode"] == "variable_weight"
    assert product["average_package_text"] == "450 g"
    assert product["purchase_increment"] == "450"
    assert product["price_variant_text"] == "450g"
    assert product["displayed_price"] == "8.42"
    assert product["displayed_unit_price"] == "18.72"
    assert product["unit_price_reference_quantity"] == "1"
    assert product["unit_price_reference_unit"] == "kg"


def test_package_normalization_prefers_mass_over_marketing_count():
    assert _normalize_package("12 unités - 450 g") == "450 g"
    assert _normalize_package("12 unités") == "12 ea"
    assert _normalize_package("1 L") == "1 l"


def test_categories_are_paths_without_query_pagination_or_search_filters():
    assert normalize_category_path("fruits-et-legumes/fruits") == (
        "/allees/fruits-et-legumes/fruits"
    )
    for invalid in (
        "recherche?filter=promo",
        "fruits-et-legumes-page-2",
        "https://example.test/allees/fruits",
    ):
        try:
            normalize_category_path(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"La catégorie {invalid!r} devait être refusée.")


def test_official_deals_filter_is_normalized_and_paginated():
    assert normalize_deals_path(
        "https://www.superc.ca/recherche?"
        "filter=%3Arelevance%3Adeal%3AToutes+les+promotions&sortOrder=relevance"
    ) == DEALS_PATH
    assert _deals_page_path(DEALS_PATH, 1) == DEALS_PATH
    assert _deals_page_path(DEALS_PATH, 3) == (
        "/recherche-page-3?sortOrder=relevance&"
        "filter=%3Arelevance%3Adeal%3AToutes+les+promotions"
    )

    try:
        normalize_deals_path("/recherche?sortOrder=relevance&filter=prix")
    except ValueError:
        pass
    else:
        raise AssertionError("Un filtre Super C arbitraire devait être refusé.")


def test_deals_pagination_uses_the_last_link_instead_of_catalogue_math():
    parser = SuperCPageParser()
    parser.feed(HTML)

    assert _expected_page_count(parser, "category") == 41
    assert _expected_page_count(parser, "weekly_deals") == 2


def test_deals_capture_uses_the_weekly_deals_listing(monkeypatch):
    extractor = SuperCWebExtractor("640", request_delay_seconds=0)
    monkeypatch.setattr(extractor, "_verify_store", lambda html: None)
    requested = []

    def request(url, **_kwargs):
        requested.append(url)
        return HTML

    monkeypatch.setattr(extractor, "_request", request)
    pages = extractor.capture_deals(DEALS_PATH, max_pages=1)

    assert requested == [f"https://www.superc.ca{DEALS_PATH}"]
    assert pages[0]["listing_kind"] == "weekly_deals"


def test_extractor_reports_page_and_product_progress(monkeypatch):
    extractor = SuperCWebExtractor("640", request_delay_seconds=0)
    monkeypatch.setattr(extractor, "_verify_store", lambda html: None)
    monkeypatch.setattr(extractor, "_request", lambda url, **_kwargs: HTML)
    updates = []

    pages = extractor.capture_category(
        "fruits-et-legumes/fruits",
        max_pages=1,
        progress=lambda page, total_pages, captured, total: updates.append(
            (page, total_pages, captured, total)
        ),
    )

    assert len(pages) == 1
    assert updates == [(1, 41, 2, 81)]


def test_extractor_persists_each_page_through_callback(monkeypatch):
    extractor = SuperCWebExtractor("640", request_delay_seconds=0)
    monkeypatch.setattr(extractor, "_verify_store", lambda html: None)
    monkeypatch.setattr(extractor, "_request", lambda url, **_kwargs: HTML)
    saved = []

    extractor.capture_category(
        "fruits-et-legumes/fruits",
        max_pages=1,
        page_captured=lambda page, payload: saved.append((page, payload)),
    )

    assert saved[0][0] == 1
    assert saved[0][1]["products"][0]["retailer_product_id"] == "059749892582"


def test_duplicate_page_does_not_stop_the_remaining_catalogue(monkeypatch):
    extractor = SuperCWebExtractor("640", request_delay_seconds=0)
    monkeypatch.setattr(extractor, "_verify_store", lambda html: None)
    # 4 produits annoncés, 2 tuiles par page : l'estimation donne 2 pages.
    # La page 2 est un doublon, donc les 2 derniers produits ne peuvent
    # arriver qu'en page 3 — au-delà de l'estimation. S'arrêter dessus
    # tronquait le rayon de moitié en silence.
    first = HTML.replace('data-total-results="81"', 'data-total-results="4"')
    third = first.replace("059749892582", "999999999991").replace(
        "4011", "999999999992"
    )
    responses = iter([first, first, third])
    monkeypatch.setattr(
        extractor, "_request", lambda url, **_kwargs: next(responses)
    )

    pages = extractor.capture_category("fruits-et-legumes/fruits")

    assert len(pages) == 2
    assert pages[1]["products"][0]["retailer_product_id"] == "999999999991"
    assert sum(len(page["products"]) for page in pages) == 4


def _extractor(monkeypatch, responses):
    extractor = SuperCWebExtractor("640", request_delay_seconds=0)
    monkeypatch.setattr(extractor, "_verify_store", lambda html: None)
    stream = iter(responses)
    monkeypatch.setattr(
        extractor, "_request", lambda url, **_kwargs: next(stream, responses[-1])
    )
    return extractor


def test_a_listing_without_an_announced_total_is_refused_not_capped_at_one_page():
    """Test discriminant : `total or len(products)` donnait ceil(n/n) = 1.

    Un attribut renommé côté site suffisait à réduire un rayon entier à sa
    première page, sans qu'aucun compteur ne bouge et sans qu'aucune
    exception ne soit levée.
    """
    parser = SuperCPageParser()
    parser.feed(HTML.replace(' data-total-results="81"', ""))

    assert parser.total_results is None
    assert parser.products, "la page expose bien des tuiles"

    try:
        _expected_page_count(parser, "category")
    except SuperCCaptureIncomplete:
        pass
    else:
        raise AssertionError(
            "Sans total annoncé, le rayon était silencieusement plafonné à 1 page."
        )


def test_a_first_page_without_tiles_is_refused_when_the_listing_claims_results(
    monkeypatch,
):
    """Un rayon vide et une lecture cassée rendaient tous deux []."""
    extractor = _extractor(
        monkeypatch, ['<div class="plpGridList" data-total-results="5"></div>']
    )

    try:
        extractor.capture_category("fruits-et-legumes/fruits")
    except SuperCCaptureIncomplete:
        pass
    else:
        raise AssertionError(
            "5 résultats annoncés et aucune tuile lue devait être refusé."
        )


def test_a_listing_that_yields_fewer_products_than_announced_is_refused(monkeypatch):
    """Le compte annoncé était rapporté au `progress`, jamais confronté.

    C'est la troncature que produit une pagination qui ne lie qu'une fenêtre
    de pages : la capture s'arrête, rend un rayon amputé, et rien ne le dit.
    """
    first = HTML.replace('data-total-results="81"', 'data-total-results="10"')
    empty = '<div class="plpGridList" data-total-results="10"></div>'
    extractor = _extractor(monkeypatch, [first, empty, empty, empty])

    try:
        extractor.capture_category("fruits-et-legumes/fruits")
    except SuperCCaptureIncomplete as error:
        assert "10" in str(error), "l'écart doit nommer les deux nombres"
    else:
        raise AssertionError("2 produits sur 10 annoncés devait être refusé.")


def test_an_explicitly_bounded_capture_stays_legitimate(monkeypatch):
    """`max_pages` est la seule troncature que l'appelant a demandée."""
    first = HTML.replace('data-total-results="81"', 'data-total-results="10"')
    extractor = _extractor(monkeypatch, [first])

    pages = extractor.capture_category("fruits-et-legumes/fruits", max_pages=1)

    assert len(pages) == 1


class _Response:
    def __init__(self, body: str):
        self._body = body.encode()
        self.headers = Message()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


def test_retry_rotates_proxy_and_keeps_credentials_out_of_logs(monkeypatch, caplog):
    import app.adapters.superc_web as web

    class _BlockedOpener:
        def open(self, request, timeout):
            raise HTTPError(
                request.full_url,
                429,
                "rate limited",
                Message(),
                BytesIO(),
            )

    class _WorkingOpener:
        def open(self, request, timeout):
            return _Response("ok")

    openers = iter([_BlockedOpener(), _WorkingOpener()])
    monkeypatch.setattr(web, "build_opener", lambda *_handlers: next(openers))
    monkeypatch.setattr(web.time, "sleep", lambda _seconds: None)
    extractor = SuperCWebExtractor(
        "640",
        request_delay_seconds=0,
        request_jitter_seconds=0,
        retries=1,
        proxies=[
            "http://secret-user:secret-pass@proxy-1.test:8080",
            "http://proxy-2.test:8080",
        ],
    )

    assert extractor._request("https://www.superc.ca/test") == "ok"
    assert "secret-user" not in caplog.text
    assert "secret-pass" not in caplog.text


def test_each_proxy_selects_the_store_with_its_own_cookie_session(monkeypatch):
    import app.adapters.superc_web as web

    class _RecordingOpener:
        def __init__(self):
            self.urls = []

        def open(self, request, timeout):
            self.urls.append(request.full_url)
            return _Response("var userStoreId = 640;")

    created = []

    def make_opener(*_handlers):
        opener = _RecordingOpener()
        created.append(opener)
        return opener

    monkeypatch.setattr(web, "build_opener", make_opener)
    extractor = SuperCWebExtractor(
        "640",
        request_delay_seconds=0,
        request_jitter_seconds=0,
        proxies=["http://proxy-1.test:8080", "http://proxy-2.test:8080"],
    )

    extractor._request("https://www.superc.ca/allees/test", requires_store=True)
    extractor._rotate_identity()
    extractor._request("https://www.superc.ca/allees/test", requires_store=True)

    assert len(created) == 2
    for opener in created:
        assert opener.urls == [
            "https://www.superc.ca/",
            "https://www.superc.ca/stores/my-store/640",
            "https://www.superc.ca/allees/test",
        ]


def test_retry_after_accepts_seconds_and_http_dates():
    assert _retry_after_seconds("17") == 17
    assert _retry_after_seconds(
        "Thu, 13 Aug 2026 16:00:30 GMT",
        now=datetime(2026, 8, 13, 16, 0, 0, tzinfo=timezone.utc),
    ) == 30


def test_request_delay_adds_bounded_jitter(monkeypatch):
    import app.adapters.superc_web as web

    sleeps = []
    monkeypatch.setattr(web.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(web.time, "sleep", sleeps.append)
    monkeypatch.setattr(web.random, "uniform", lambda start, end: 1.5)
    extractor = SuperCWebExtractor(
        "640", request_delay_seconds=10, request_jitter_seconds=2
    )
    extractor._last_request_at = 100.0
    extractor._identities[0].opener = type(
        "WorkingOpener",
        (),
        {"open": lambda self, request, timeout: _Response("ok")},
    )()

    assert extractor._request("https://www.superc.ca/test") == "ok"
    assert sleeps == [11.5]
