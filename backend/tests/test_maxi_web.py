"""Contrats du collecteur navigateur Maxi, sans lancer de navigateur."""

from app.adapters.maxi_web import (
    _money,
    _page_url,
    normalize_category_url,
    product_from_snapshot,
)


def test_price_needs_a_currency_anchor_and_multi_buy_is_divided():
    """Test discriminant : le premier nombre du texte n'est pas le prix.

    Sans ancre de devise, « 2/5,00 $ » se lisait 2,00 $ — un rabais de
    circulaire devenait le prix le plus bas du rayon et remportait chaque
    sélection en aval. Super C porte déjà cette ancre ; c'est Maxi qui
    divergeait.
    """
    # Le défaut nommé : un multi-achat vaut son quotient, pas son premier
    # nombre ni son montant total.
    assert _money("2/5,00 $") == "2.50"
    assert _money("2 pour 5,00 $") == "2.50"
    assert _money("3 for $5.00") == "1.67"

    # Les deux positions du symbole que Maxi rend selon la langue de la fiche.
    assert _money("5,00 $") == "5.00"
    assert _money("$5.00") == "5.00"

    # Sans devise mais sans ambiguïté non plus : un seul nombre reste lisible,
    # pour ne pas perdre les fiches dont le DOM ne porte pas le symbole.
    assert _money("14.99") == "14.99"

    # Plusieurs nombres et aucune devise : c'est exactement le cas où
    # l'ancienne lecture prenait le mauvais. Refuser coûte moins cher.
    assert _money("2 kg, 0,75 / 100 g") is None
    assert _money("") is None
    assert _money(None) is None


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
