"""Prix historiques — essentiels (staples), pilote, docs/product-pilot.md.

Distinct de ``validation.py::min_taxed_price_per_base_unit`` (qui n'opère
que sur un ``ProblemData`` déjà chargé, aux prix valides à une date
précise) : ici, la fenêtre couvre la dernière année, ce qui exige de
requêter la base directement — ``market.price`` conserve tout son
historique (aucune ligne écrasée), donc aucune donnée supplémentaire à
stocker pour cette fonctionnalité.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Price, Product


def historical_min_price_per_base_unit(
    session: Session, on_date: date, window_days: int = 365,
) -> dict[str, Decimal]:
    """min_{p,s} c_ps(1+t_p)/v_p par ingrédient, sur tout prix dont
    ``valid_from`` tombe dans les ``window_days`` derniers jours (365 par
    défaut) — pas seulement les prix valides aujourd'hui.

    Sert uniquement à évaluer un essentiel (staple) dans l'**objectif** du
    solveur (``solver/model.py::_purchases_expr_cents``), pour biaiser le
    *choix* de recettes vers celles utilisant des ingrédients que le
    ménage est supposé déjà avoir — jamais dans le rapport des montants
    réellement déboursés (``_build_result``/``_objective_terms``
    continuent de lire les prix courants, pas ceux-ci).
    """
    window_start = on_date - timedelta(days=window_days)
    rows = session.scalars(
        select(Price).where(
            Price.valid_from >= window_start, Price.valid_from <= on_date,
        )
    ).all()
    product_ids = {p.product_id for p in rows}
    products = {
        p.id: p
        for p in session.scalars(select(Product).where(Product.id.in_(product_ids)))
    }
    best: dict[str, Decimal] = {}
    for price in rows:
        prod = products[price.product_id]
        per_unit = (
            Decimal(price.price_cents_cad)
            * (1 + prod.tax_rate)
            / prod.package_qty_in_base_unit
        )
        iid = prod.canonical_ingredient_id
        if iid not in best or per_unit < best[iid]:
            best[iid] = per_unit
    return best
