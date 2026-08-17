"""Contrats du collecteur navigateur Maxi, sans lancer de navigateur."""

from app.adapters.maxi_web import (
    _page_url,
    normalize_category_url,
    product_from_snapshot,
)


def test_category_url_is_restricted_to_maxi_and_drops_query_string():
    assert normalize_category_url(
        "https://maxi.ca/fr/alimentation/c/27985?page=4"
    ) == "https://www.maxi.ca/fr/alimentation/c/27985"


def test_official_weekly_deals_url_is_accepted_but_other_collections_are_not():
    assert normalize_category_url(
        "https://maxi.ca/fr/collection/deals-centre-value?navid=flyout"
    ) == "https://www.maxi.ca/fr/collection/deals-centre-value"

    try:
        normalize_category_url("https://www.maxi.ca/fr/collection/my-shop-deals")
    except ValueError:
        pass
    else:
        raise AssertionError("Une collection Maxi arbitraire devait être refusée.")


def test_page_url_replaces_page_parameter():
    assert _page_url(
        "https://www.maxi.ca/fr/alimentation/c/27985?foo=bar&page=2", 3
    ) == "https://www.maxi.ca/fr/alimentation/c/27985?foo=bar&page=3"


def test_promotion_snapshot_becomes_capture_product():
    product = product_from_snapshot(
        {
            "id": "20070132001_EA",
            "name": " Concombres anglais ",
            "href": "/fr/concombres-anglais/p/20070132001_EA?source=nspt",
            "brand": "",
            "package_text": "1 ea, 1,25 $/1ch",
            "regular_price": "1,44 $",
            "sale_price": "1,25 $",
            "card_text": "sale: 1,25 $, formerly: 1,44 $",
        },
        category_url="https://www.maxi.ca/fr/alimentation/c/27985?page=1",
    )

    assert product == {
        "retailer_product_id": "20070132001_EA",
        "upc": None,
        "name": "Concombres anglais",
        "brand": None,
        "package_text": "1 ea, 1,25 $/1ch",
        "displayed_price": "1.25",
        "displayed_regular_price": "1.44",
        "displayed_sale_price": "1.25",
        "is_promo": True,
        "product_url": "https://www.maxi.ca/fr/concombres-anglais/p/20070132001_EA",
        "category_url": "https://www.maxi.ca/fr/alimentation/c/27985?page=1",
        "in_listing": True,
    }


def test_out_of_stock_product_is_retained_as_evidence_but_not_listed():
    product = product_from_snapshot(
        {
            "id": "20064825001_EA",
            "name": "Smooth Peanut Butter",
            "href": "/smooth-peanut-butter/p/20064825001_EA",
            "brand": "Kraft",
            "package_text": "2 kg, $0.75/100g",
            "regular_price": "$14.99",
            "sale_price": "",
            "card_text": "Rupture de stock",
        },
        category_url="https://www.maxi.ca/fr/alimentation/c/27985?page=1",
    )

    assert product["displayed_price"] == "14.99"
    assert product["is_promo"] is False
    assert product["in_listing"] is False
