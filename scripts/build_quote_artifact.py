"""Rendre le rapport de devis hebdomadaire en une page lisible.

La page ne calcule rien : tout ce qu'elle affiche vient de
``recipe-quotes-<semaine>.json``, produit par ``quote_recipes.py``. Elle rend
visibles trois choses que le rapport porte mais qu'un tableau de totaux
masque : le panier réellement acheté, le défaut de vraisemblance d'une
recette importée, et la provenance de chaque conversion.
"""

from __future__ import annotations

import argparse
import html
import json
import statistics
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_PUBLISHED = "Format publié par le détaillant"
_LABELS = {
    "exact": "exact",
    "audited_conversion": "conversion sourcée",
    "estimated": "estimé",
    "incomplete": "non chiffrable",
}
_FLAG_LABELS = {
    "duplicate_ingredient": "ingrédient compté deux fois",
    "implausible_quantity": "quantité invraisemblable",
    "implausible_servings": "portions douteuses",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--seed-dir", type=Path, default=ROOT / "seed" / "main")
    parser.add_argument("--store-label", default="Super C (magasin 640)")
    parser.add_argument("--period", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    canonical = {
        row["id"]: row
        for row in json.loads(
            (args.seed_dir / "canonical_ingredients.json").read_text(encoding="utf-8")
        )
    }
    imported = {
        row["id"]
        for row in json.loads(
            (args.seed_dir / "imported_recipes.json").read_text(encoding="utf-8")
        )
    }
    page = _render(report, canonical, imported, args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding="utf-8")
    print(f"Artefact écrit: {args.output} ({len(page) // 1024} ko)")
    return 0


# --------------------------------------------------------------------------
# Mise en forme


def _money(cents) -> str:
    if cents is None:
        return "—"
    value = (Decimal(str(cents)) / 100).quantize(Decimal("0.01"))
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _qty(value) -> str:
    number = Decimal(str(value))
    text = format(number.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if "." in text:
        whole, _, frac = text.partition(".")
        text = f"{whole},{frac[:2]}"
    return text


def _unit_label(base_unit: str) -> str:
    return {"g": "g", "ml": "ml", "unit": "unité(s)"}.get(base_unit, base_unit)


def _unit_price(product: dict, base_unit: str) -> tuple[str, str]:
    """Prix unitaire taxé, exprimé dans l'unité de la recette."""
    price = product.get("price_cents_cad")
    qty = product.get("package_qty_in_base_unit")
    if price is None or qty in (None, "0"):
        return "—", ""
    taxed = Decimal(str(price)) * (1 + Decimal(str(product.get("tax_rate") or "0")))
    per_base = taxed / Decimal(str(qty))
    if base_unit in {"g", "ml"}:
        return _money(per_base * 100) + " $", f"/ 100 {base_unit}"
    return _money(per_base) + " $", "/ unité"


def _package_display(product: dict) -> str:
    """Le format publié — jamais un total reconstitué pour un produit au poids."""
    brand = product.get("brand") or ""
    if brand == "Marque non indiquée":
        brand = ""
    if product.get("sale_mode") == "variable_weight":
        return "vendu au poids" + (f" · {brand}" if brand else "")
    parts = [product.get("package_unit") or "format non publié"]
    if brand:
        parts.append(brand)
    head = " · ".join(parts)
    price = product.get("price_cents_cad")
    return f"{head} — {_money(price)} $" if price is not None else head


def _tag(confidence: str, note: str = "") -> str:
    label = _LABELS.get(confidence, confidence)
    return f'<span class="tag t-{confidence}">{label}</span>{note}'


def _e(text) -> str:
    return html.escape(str(text if text is not None else ""))


# --------------------------------------------------------------------------
# Notes de provenance


class Footnotes:
    def __init__(self) -> None:
        self._order: list[str] = []

    def ref(self, text: str | None) -> str:
        if not text or text == _PUBLISHED:
            return ""
        if text not in self._order:
            self._order.append(text)
        return f'<sup class="ref">[{self._order.index(text) + 1}]</sup>'

    def items(self) -> list[str]:
        return list(self._order)


# --------------------------------------------------------------------------
# Rendu


def _render(report, canonical, imported, args) -> str:
    products = report.get("products", {})
    notes = Footnotes()
    quotes = report["quotes"]
    curated = [q for q in quotes if q["recipe_id"] not in imported]
    scraped = [q for q in quotes if q["recipe_id"] in imported]

    body = [
        _masthead(report, args),
        _tiles(report, quotes, curated),
        _reading_note(),
        _controls(),
    ]
    body.append(
        _section(
            "Recettes curées",
            "Quantités et portions vérifiées à la main. Ce sont les prix auxquels se fier.",
            curated,
            canonical,
            products,
            notes,
        )
    )
    body.append(
        _section(
            "Recettes importées",
            "Quantités issues d'un import automatique, jamais relues. Celles qui "
            "portent un avertissement ont un défaut identifié dans la recette "
            "elle-même : leur prix est indicatif, pas fiable.",
            scraped,
            canonical,
            products,
            notes,
        )
    )
    body.append(_notes_section(notes))
    body.append(_footer(report, args))
    return _SHELL.format(
        # Le titre nomme l'artefact publié : il reste stable d'une semaine à
        # l'autre dans sa forme, sinon la page change d'identité à chaque
        # republication.
        title=f"Devis Souschef {report['week'].split('-')[-1]}",
        style=_STYLE,
        body="\n".join(body),
        script=_SCRIPT,
    )


def _masthead(report, args) -> str:
    period = f" · {args.period}" if args.period else ""
    return f"""<header class="masthead">
  <h1>Le prix de chaque recette</h1>
  <p>Prix relevés chez {_e(args.store_label)}{_e(period)}.</p>
  <span class="stamp disp">{_e(report['week'])}</span>
</header>"""


def _tiles(report, quotes, curated) -> str:
    complete = [q for q in quotes if q["status"] == "complete"]
    flagged = [q for q in complete if q.get("quality_flags")]
    lines = sum(len(q["ingredients"]) for q in quotes)
    families = {}
    for quote in curated:
        if quote["status"] != "complete":
            continue
        family = quote["recipe_id"].removesuffix("_familial")
        per_serving = Decimal(str(quote["consumed_cost_per_serving_cents"]))
        families.setdefault(family, per_serving)
    median = statistics.median(families.values()) if families else Decimal("0")
    savings = [
        Decimal(str(q["promotional_savings_cents"]))
        for q in complete
        if q.get("promotional_savings_cents") is not None
    ]
    median_savings = statistics.median(savings) if savings else Decimal("0")
    unpriced = report["total_recipes"] - report["complete_recipes"]
    reserve = (
        f"{len(flagged)} autres chiffrés mais à vérifier, {unpriced} sans prix"
        if flagged
        else f"aucun devis chiffré ne porte de réserve, {unpriced} sans prix"
    )
    return f"""<div class="tiles">
  <div class="tile"><div class="k disp">Devis sans réserve</div>
    <div class="v num">{report['reliable_recipes']} / {report['total_recipes']}</div>
    <div class="n">{reserve}</div></div>
  <div class="tile"><div class="k disp">Médiane, recettes curées</div>
    <div class="v num">{_money(median)} $</div>
    <div class="n">par portion, sur {len(families)} plats distincts</div></div>
  <div class="tile"><div class="k disp">Lignes justifiées</div>
    <div class="v num">{lines}</div>
    <div class="n">chaque ingrédient, son produit et son prix</div></div>
  <div class="tile"><div class="k disp">Rabais médian par devis</div>
    <div class="v num">{_money(median_savings)} $</div>
    <div class="n">jamais cumulé : les devis partagent les mêmes emballages</div></div>
</div>"""


def _reading_note() -> str:
    return """<div class="note">
  <h2 class="disp">Comment lire ces montants</h2>
  <p><b>Ouvrez n'importe quelle recette</b> pour voir le calcul complet : chaque ingrédient, la
  quantité demandée, le produit retenu avec son format et son prix, le prix unitaire, et le coût
  qui en découle. Un second tableau donne le panier : ce qu'il faut réellement mettre dans le
  chariot, en emballages entiers. Les recettes sans prix indiquent quel ingrédient bloque.</p>
  <p><b>Coût consommé</b> : la valeur des quantités réellement utilisées, au meilleur prix
  unitaire du magasin. <b>Décaissement</b> : ce qu'il faut payer à la caisse pour préparer cette
  recette seule en partant de rien. Le panier retient le format qui minimise la dépense, pas le
  format le moins cher au 100 g — les deux tableaux peuvent donc citer deux produits différents,
  et le surplus est indiqué.</p>
  <p>Chaque ligne porte son niveau de confiance, y compris les lignes d'achat. <b>Exact</b> :
  format et prix publiés par le détaillant. <b>Conversion sourcée</b> : une conversion
  documentée, citée en note. <b>Estimé</b> : une quantité repose sur une hypothèse déclarée —
  contenu d'une botte, poids d'un article vendu à la pièce. Les renvois <sup class="ref">[n]</sup>
  pointent vers la liste des sources, en bas de page.</p>
</div>"""


def _controls() -> str:
    return """<div class="controls">
  <input type="search" id="q" placeholder="Chercher une recette…" aria-label="Chercher une recette">
  <button class="chip disp" data-filter="all" aria-pressed="true">Toutes</button>
  <button class="chip disp" data-filter="reliable" aria-pressed="false">Sans réserve</button>
  <button class="chip disp" data-filter="flag" aria-pressed="false">À vérifier</button>
  <button class="chip disp" data-filter="incomplete" aria-pressed="false">Sans prix</button>
  <button class="chip disp" id="openall" aria-pressed="false">Tout déplier</button>
</div>"""


def _section(title, lede, quotes, canonical, products, notes) -> str:
    complete = [q for q in quotes if q["status"] == "complete"]
    families = {q["recipe_id"].removesuffix("_familial") for q in quotes}
    rows = sorted(
        complete, key=lambda q: Decimal(str(q["consumed_cost_per_serving_cents"]))
    ) + [q for q in quotes if q["status"] != "complete"]
    heading = (
        f"{title} — {len(complete)} devis sur {len(quotes)}, "
        f"{len(families)} plats distincts"
    )
    cells = "\n".join(
        _recipe_rows(quote, index, canonical, products, notes)
        for index, quote in enumerate(rows)
    )
    return f"""<section class="group">
  <h2 class="disp">{_e(heading)}</h2>
  <p class="lede">{_e(lede)}</p>
  <div class="scroll"><table><thead><tr>
    <th class="disp">Recette</th><th class="r disp">$ / portion</th>
    <th class="r disp">Coût consommé</th><th class="r disp">Décaissement</th>
    <th class="r disp">Rabais</th><th class="disp">Confiance</th>
  </tr></thead><tbody>
{cells}
  </tbody></table></div>
  <p class="empty" hidden>Aucune recette ne correspond.</p>
</section>"""


def _recipe_rows(quote, index, canonical, products, notes) -> str:
    ident = f"{quote['recipe_id']}"
    flags = quote.get("quality_flags") or []
    warn = ""
    if flags:
        details = " · ".join(
            f"{_FLAG_LABELS.get(flag['kind'], flag['kind'])} : {flag['detail']}"
            if flag["kind"] != "implausible_servings"
            else flag["detail"]
            for flag in flags
        )
        warn = f'<span class="warn">⚠ {_e(details)}</span>'
    servings = quote["servings"]
    sub = f"{servings} portions · {len(quote['ingredients'])} ingrédients"
    if quote["status"] == "complete":
        values = (
            f'<td class="r num big">{_money(quote["consumed_cost_per_serving_cents"])}</td>'
            f'<td class="r num">{_money(quote["consumed_cost_cents"])}</td>'
            f'<td class="r num">{_money(quote["autonomous_checkout_cents"])}</td>'
            f'<td class="r num">{_money(quote["promotional_savings_cents"])}</td>'
        )
    else:
        missing = len(quote["incomplete_ingredients"])
        values = f'<td class="r miss" colspan="4">{missing} ingrédient(s) sans prix</td>'
    status = quote["status"]
    reliable = "1" if status == "complete" and not flags else "0"
    head = f"""<tr class="recipe" data-name="{_e(quote['recipe_name'].lower())}" data-status="{status}" data-flag="{'1' if flags else '0'}" data-reliable="{reliable}">
<td class="name"><button class="expand" type="button" aria-expanded="false" aria-controls="d{index}" title="Voir le détail">▸</button><button class="title" type="button" aria-expanded="false" aria-controls="d{index}">{_e(quote['recipe_name'])}</button><span class="sub num">{_e(sub)}</span>{warn}</td>
{values}<td>{_tag(quote['consumed_confidence'])}{'' if quote['checkout_confidence'] == quote['consumed_confidence'] else ' / ' + _tag(quote['checkout_confidence'])}</td></tr>"""
    detail = f"""<tr class="detail" id="d{index}" hidden><td colspan="6">
{_ingredient_table(quote, canonical, products, notes)}
{_purchase_table(quote, canonical, products, notes)}
{_missing_table(quote, canonical)}
</td></tr>"""
    return head + "\n" + detail


def _ingredient_table(quote, canonical, products, notes) -> str:
    rows = []
    for line in quote["ingredients"]:
        ingredient = canonical.get(line["ingredient_id"], {})
        name = ingredient.get("name", line["ingredient_id"])
        procurement_id = line.get("procurement_ingredient_id")
        via = ""
        if procurement_id and procurement_id != line["ingredient_id"]:
            source = canonical.get(procurement_id, {}).get("name", procurement_id)
            via = f'<span class="sub">acheté comme : {_e(source)}</span>'
        base = canonical.get(procurement_id or line["ingredient_id"], {}).get(
            "base_unit", ingredient.get("base_unit", "g")
        )
        product = products.get(line.get("product_external_key") or "", {})
        if line["resolution"] == "essential":
            product_cell = '<span class="prod">aucun achat</span>'
            price_cell = "—"
        elif not product:
            product_cell = '<span class="prod miss">aucun produit retenu</span>'
            price_cell = "—"
        else:
            product_cell = (
                f'<span class="prod">{_e(product.get("name"))}</span>'
                f'<span class="sub">{_e(_package_display(product))}</span>'
            )
            value, unit = _unit_price(product, base)
            price_cell = f'{value}<span class="sub">{_e(unit)}</span>'
        note = notes.ref(product.get("quantity_provenance")) + notes.ref(
            line.get("reason")
        )
        rows.append(
            f'<tr><td>{_e(name)}{via}</td>'
            f'<td class="r num">{_qty(line["required_quantity"])} {_e(_unit_label(ingredient.get("base_unit", base)))}</td>'
            f"<td>{product_cell}</td>"
            f'<td class="r num">{price_cell}</td>'
            f'<td class="r num">{_money(line["consumed_cost_cents"])} $</td>'
            f'<td>{_tag(line["confidence"], note)}</td></tr>'
        )
    return f"""<h3 class="disp">Comment ce prix est calculé</h3>
<div class="scroll"><table><thead><tr><th>Ingrédient</th><th class="r">Besoin</th>
<th>Produit retenu</th><th class="r">Prix unitaire</th><th class="r">Coût</th>
<th>Confiance</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>"""


def _purchase_table(quote, canonical, products, notes) -> str:
    if not quote["purchases"]:
        return ""
    rows = []
    for line in quote["purchases"]:
        product = products.get(line["product_external_key"], {})
        ingredient = canonical.get(line["procurement_ingredient_id"], {})
        base = ingredient.get("base_unit", "g")
        surplus = Decimal(str(line["surplus_quantity"]))
        surplus_cell = (
            f'{_qty(surplus)} {_e(_unit_label(base))}' if surplus > 0 else "—"
        )
        units = Decimal(str(line["purchase_units"]))
        units_cell = (
            f"{_qty(units)} ×" if line["sale_mode"] == "fixed_package" else "au poids"
        )
        rows.append(
            f'<tr><td>{_e(ingredient.get("name", line["procurement_ingredient_id"]))}'
            f'<span class="sub">{_e(product.get("name"))}</span></td>'
            f'<td>{_e(_package_display(product))}</td>'
            f'<td class="r num">{units_cell}</td>'
            f'<td class="r num">{_qty(line["purchased_quantity"])} {_e(_unit_label(base))}</td>'
            f'<td class="r num">{surplus_cell}</td>'
            f'<td class="r num">{_money(line["checkout_cost_cents"])} $</td>'
            f'<td>{_tag(line["confidence"], notes.ref(product.get("quantity_provenance")))}</td></tr>'
        )
    return f"""<h3 class="disp">Ce qu'il faut acheter</h3>
<div class="scroll"><table><thead><tr><th>Ingrédient</th><th>Produit et format</th>
<th class="r">Unités</th><th class="r">Obtenu</th><th class="r">Surplus</th>
<th class="r">Payé</th><th>Confiance</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>"""


def _missing_table(quote, canonical) -> str:
    if not quote["incomplete_ingredients"]:
        return ""
    rows = "".join(
        f'<tr><td class="miss">{_e(canonical.get(item, {}).get("name", item))}</td>'
        f"<td colspan=\"5\">aucun produit approuvé chez ce détaillant</td></tr>"
        for item in quote["incomplete_ingredients"]
    )
    return f"""<h3 class="disp">Pourquoi cette recette n'a pas de prix</h3>
<div class="scroll"><table><tbody>{rows}</tbody></table></div>"""


def _notes_section(notes) -> str:
    items = "".join(f"<li>{_e(text)}</li>" for text in notes.items())
    return f"""<section class="group notes">
  <h2 class="disp">Sources des conversions et des hypothèses</h2>
  <p class="lede">Chaque fois qu'un format du détaillant a dû être traduit dans l'unité de la
  recette, voici sur quoi la conversion s'appuie.</p>
  <ol>{items}</ol>
</section>"""


def _footer(report, args) -> str:
    return f"""<footer>
  Source : <code>{_e(args.report.as_posix())}</code>, produit par
  <code>scripts/quote_recipes.py</code> puis rendu par
  <code>scripts/build_quote_artifact.py</code>. Un seul détaillant : aucun de ces prix n'est
  un « meilleur prix » entre bannières. Les taxes sont appliquées par rayon selon
  <code>config/quebec-tax-rates.json</code> : l'épicerie de base est détaxée, l'alcool et la
  confiserie ne le sont pas.
</footer>"""


_STYLE = """
:root {
  color-scheme: light;
  --ground: #F3ECDD; --card: #FBF6EC; --ink: #241A12; --ink-soft: #6B5B49;
  --rule: #D6C7AC; --rule-strong: #B9A583; --brick: #9E3B23; --bordeaux: #6B1F2C;
  --forest: #33573C; --amber: #8A5A0F; --shade: #EDE4D2; --sunk: #E6DBC5;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --ground: #15110D; --card: #1E1913; --ink: #EFE5D3; --ink-soft: #A79781;
    --rule: #3A3128; --rule-strong: #574A3B; --brick: #D9754F; --bordeaux: #D2687C;
    --forest: #7FB88C; --amber: #D9A441; --shade: #241E17; --sunk: #191410;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --ground: #15110D; --card: #1E1913; --ink: #EFE5D3; --ink-soft: #A79781;
  --rule: #3A3128; --rule-strong: #574A3B; --brick: #D9754F; --bordeaux: #D2687C;
  --forest: #7FB88C; --amber: #D9A441; --shade: #241E17; --sunk: #191410;
}
* { box-sizing: border-box; }
body { margin: 0; padding: 0 20px 72px; background: var(--ground); color: var(--ink);
  font: 16px/1.55 Georgia, "Times New Roman", serif; }
.wrap { max-width: 1120px; margin: 0 auto; }
.disp { font-family: "Arial Narrow", "Helvetica Neue Condensed", Arial, sans-serif;
  font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; }
.num { font-family: "Courier New", Courier, monospace; font-variant-numeric: tabular-nums; }
header.masthead { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 18px;
  padding: 34px 0 16px; border-bottom: 3px double var(--rule-strong); }
header.masthead h1 { margin: 0; font-size: clamp(28px, 4.4vw, 42px); line-height: 1.05; text-wrap: balance; }
header.masthead p { margin: 0; color: var(--ink-soft); font-size: 15px; }
.stamp { margin-left: auto; padding: 4px 10px; border: 1px solid var(--rule-strong);
  color: var(--brick); font-size: 12px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(168px, 1fr)); gap: 1px;
  background: var(--rule); border: 1px solid var(--rule); margin: 26px 0 0; }
.tile { background: var(--card); padding: 16px 18px; }
.tile .k { font-size: 11px; color: var(--ink-soft); }
.tile .v { font-size: 30px; line-height: 1.1; margin-top: 6px; color: var(--brick); }
.tile .n { font-size: 13px; color: var(--ink-soft); margin-top: 4px; }
.note { border-left: 3px solid var(--brick); background: var(--shade); padding: 16px 20px; margin: 26px 0 0; }
.note h2 { margin: 0 0 8px; font-size: 13px; }
.note p { margin: 0 0 10px; font-size: 15px; max-width: 68ch; }
.note p:last-child { margin-bottom: 0; }
.note b { color: var(--brick); }
.controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin: 30px 0 14px; }
.controls input[type="search"] { flex: 1 1 220px; min-width: 180px; padding: 9px 12px;
  background: var(--card); border: 1px solid var(--rule-strong); color: var(--ink); font: inherit; font-size: 15px; }
.chip { padding: 7px 13px; border: 1px solid var(--rule-strong); background: var(--card);
  color: var(--ink-soft); font-size: 12px; cursor: pointer; }
.chip[aria-pressed="true"] { background: var(--brick); border-color: var(--brick); color: var(--card); }
.chip:focus-visible, input:focus-visible, button:focus-visible { outline: 2px solid var(--brick); outline-offset: 2px; }
section.group { margin-top: 34px; }
section.group > h2 { margin: 0 0 4px; font-size: 15px; color: var(--brick); }
section.group > p.lede { margin: 0 0 12px; color: var(--ink-soft); font-size: 14px; max-width: 72ch; }
.scroll { overflow-x: auto; border: 1px solid var(--rule); background: var(--card); }
table { width: 100%; border-collapse: collapse; font-size: 15px; }
thead th { background: var(--shade); text-align: left; border-bottom: 1px solid var(--rule-strong);
  padding: 10px 12px; white-space: nowrap; color: var(--ink-soft); font-size: 11px; }
thead th.r, td.r { text-align: right; }
tbody td { padding: 9px 12px; border-bottom: 1px solid var(--rule); vertical-align: top; }
tbody tr.recipe:hover td { background: var(--shade); }
td.name { min-width: 250px; }
.sub { display: block; font-size: 12px; color: var(--ink-soft); }
td.r { white-space: nowrap; }
.big { font-size: 16px; }
button.expand { background: none; border: 0; padding: 0; margin: 0 6px 0 0; cursor: pointer;
  color: var(--brick); font: inherit; font-size: 13px; width: 1.1em; }
button.title { background: none; border: 0; padding: 0; color: inherit; font: inherit;
  text-align: left; cursor: pointer; }
button.title:hover { color: var(--brick); }
.tag { display: inline-block; padding: 1px 7px; border: 1px solid currentColor; font-size: 10.5px;
  font-family: "Arial Narrow", Arial, sans-serif; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.05em; white-space: nowrap; }
.t-exact { color: var(--forest); }
.t-audited_conversion { color: var(--brick); }
.t-estimated { color: var(--amber); }
.t-incomplete { color: var(--ink-soft); }
.warn { color: var(--bordeaux); font-size: 12px; display: block; margin-top: 3px; }
tr.detail > td { background: var(--sunk); padding: 0 12px 14px; border-bottom: 2px solid var(--rule-strong); }
tr.detail table { font-size: 13.5px; margin-top: 4px; }
tr.detail thead th { background: none; border-bottom: 1px solid var(--rule); font-size: 10.5px; padding: 8px 8px; }
tr.detail tbody td { padding: 6px 8px; border-bottom: 1px dotted var(--rule); }
tr.detail tbody tr:last-child td { border-bottom: 0; }
.prod { display: block; }
.miss { color: var(--bordeaux); }
sup.ref { font-size: 10px; color: var(--brick); }
.detail h3, tr.detail h3 { margin: 14px 0 2px; font-size: 11px; color: var(--ink-soft); }
.notes ol { padding-left: 22px; margin: 8px 0 0; }
.notes li { margin-bottom: 7px; font-size: 13.5px; color: var(--ink-soft); max-width: 88ch; }
.empty { padding: 22px; color: var(--ink-soft); font-size: 15px; }
footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--rule);
  color: var(--ink-soft); font-size: 13px; max-width: 76ch; }
footer code { font-family: "Courier New", monospace; font-size: 12px; color: var(--brick); }
@media (max-width: 640px) { td.name { min-width: 180px; } .tile .v { font-size: 24px; } }
"""

_SCRIPT = """
(function () {
  var q = document.getElementById('q');
  var chips = Array.prototype.slice.call(document.querySelectorAll('.chip[data-filter]'));
  var filter = 'all';

  function setOpen(tr, open) {
    var detail = document.getElementById(tr.querySelector('.expand').getAttribute('aria-controls'));
    if (!detail) return;
    detail.hidden = !open;
    tr.querySelectorAll('[aria-expanded]').forEach(function (b) {
      b.setAttribute('aria-expanded', String(open));
    });
    tr.querySelector('.expand').textContent = open ? '\\u25BE' : '\\u25B8';
  }

  document.querySelectorAll('tr.recipe').forEach(function (tr) {
    tr.querySelectorAll('.expand, .title').forEach(function (button) {
      button.addEventListener('click', function () {
        setOpen(tr, tr.querySelector('.expand').getAttribute('aria-expanded') !== 'true');
      });
    });
  });

  function matches(tr) {
    if (filter === 'all') return true;
    if (filter === 'flag') return tr.dataset.flag === '1';
    if (filter === 'reliable') return tr.dataset.reliable === '1';
    return tr.dataset.status === filter;
  }

  function apply() {
    var term = q.value.trim().toLowerCase();
    document.querySelectorAll('section.group').forEach(function (section) {
      var shown = 0;
      section.querySelectorAll('tr.recipe').forEach(function (tr) {
        var show = (!term || tr.dataset.name.indexOf(term) !== -1) && matches(tr);
        tr.hidden = !show;
        if (!show) setOpen(tr, false);
        if (show) shown++;
      });
      var empty = section.querySelector('.empty');
      if (empty) empty.hidden = shown !== 0;
    });
  }

  q.addEventListener('input', apply);
  chips.forEach(function (chip) {
    chip.addEventListener('click', function () {
      filter = chip.dataset.filter;
      chips.forEach(function (c) { c.setAttribute('aria-pressed', String(c === chip)); });
      apply();
    });
  });

  var openall = document.getElementById('openall');
  openall.addEventListener('click', function () {
    var open = openall.getAttribute('aria-pressed') !== 'true';
    openall.setAttribute('aria-pressed', String(open));
    openall.textContent = open ? 'Tout replier' : 'Tout d\\u00e9plier';
    document.querySelectorAll('tr.recipe').forEach(function (tr) {
      if (!tr.hidden) setOpen(tr, open);
    });
  });
})();
"""

_SHELL = """<title>{title}</title>
<style>{style}</style>
<div class="wrap">
{body}
</div>
<script>{script}</script>
"""


if __name__ == "__main__":
    raise SystemExit(main())
