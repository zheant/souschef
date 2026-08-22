"""Lire une page de recette et en proposer une recette de la base.

Le script **propose**; il n'importe rien tout seul. Une page donne un brouillon,
chaque ligne d'ingrédient donne une proposition — quantité, unité, ingrédient
canonique visé — et le tout est écrit dans une file de revue. C'est la règle du
dépôt pour toute décision de curation : proposer, jamais rattacher sur une
ressemblance (D32, `scripts/propose_cnf_matches.py`).

Ce qu'une proposition porte, et pourquoi ça se relit. Trois choses peuvent avoir
l'air justes et être fausses :

- **la ligne n'a pas de quantité** (« Au goût ») — rien à mettre dans une
  recette;
- **aucun alias ne nomme l'ingrédient** — le canon ne connaît pas cette matière,
  ou pas sous ce nom;
- **la dimension ne correspond pas** — « 22,5 ml d'ail » vise un ingrédient qui
  se compte à la gousse. Convertir demanderait une équivalence curée, et
  l'inventer serait pire que refuser.

Et une quatrième, que seul un humain voit : « tomates italiennes entières,
796 ml » se résout vers la tomate *fraîche* alors que 796 ml est une conserve.
C'est exactement pourquoi la confirmation est humaine.

Exemples :
  python scripts/import_recipe_from_url.py --url https://exemple.ca/recettes/x
  python scripts/import_recipe_from_url.py --review data/recipe-import-review/url/x.json --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (str(BACKEND), str(Path(__file__).resolve().parent)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.ingestion.recipe_web_source import FixtureRecipePage, UrlRecipePage
# La conversion vers l'unité de base vient de l'importateur de recettes, pas
# d'une seconde table de facteurs : une tasse doit valoir la même chose dans les
# deux chemins d'import, et deux tables finiraient par diverger.
from import_cook_recipes import _converted_quantity, _volume_ml
from app.services.recipe_web_extraction import (
    ExtractionRefused,
    dimension_of,
    extract_recipe,
    parse_ingredient_line,
    resolve_canonical,
)

REVIEW_DIR = ROOT / "data" / "recipe-import-review" / "url"

#: L'unité de base du canon, par dimension : c'est la comparaison qui dit si une
#: ligne est convertible sans inventer une équivalence.
_DIMENSION_OF_BASE_UNIT = {"g": "mass", "ml": "volume", "unit": "count"}


def _aliases(seed_dir: Path) -> dict[str, str]:
    """Alias du canon, plus le nom de chaque ingrédient : les pages écrivent
    souvent le nom canonique lui-même."""
    aliases: dict[str, str] = {}
    for row in json.loads(
        (seed_dir / "canonical_ingredient_aliases.json").read_text(encoding="utf-8")
    ):
        aliases.setdefault(row["normalized_alias"], row["canonical_ingredient_id"])
    for row in json.loads(
        (seed_dir / "canonical_ingredients.json").read_text(encoding="utf-8")
    ):
        aliases.setdefault(row["name"].lower(), row["id"])
    return aliases


def _catalogue(seed_dir: Path) -> dict[str, dict]:
    return {
        row["id"]: row
        for row in json.loads(
            (seed_dir / "canonical_ingredients.json").read_text(encoding="utf-8")
        )
    }


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "recette"


def _to_base_quantity(
    quantity: Decimal, unit: str | None, canonical: dict, curation: dict
) -> tuple[Decimal | None, bool, str | None]:
    """Quantité dans l'unité de base du canon : (valeur, estimée, blocage).

    La cascade est celle de l'importateur de recettes, dans le même ordre et sur
    le même fichier de curation — pas une seconde table. D'abord une conversion
    de même dimension (ml → l, g → kg). Ensuite les équivalences curées :
    la densité d'un ingrédient mesuré en volume mais pesé au gramme (une épice
    en cuillère), puis la masse par article d'un ingrédient dénombré. Une masse
    seulement *estimée* est retenue, mais dite : la recette portera la mention,
    comme l'importateur le fait déjà.
    """
    base_unit = canonical["base_unit"]
    direct = _converted_quantity(quantity, unit, base_unit)
    if direct is not None:
        return direct, False, None

    ingredient_id = canonical["id"]
    if base_unit == "g":
        millilitres = _volume_ml(quantity, unit)
        density = curation.get("grams_per_millilitre", {}).get(ingredient_id)
        if millilitres is not None and density is not None:
            return millilitres * Decimal(str(density)), False, None
        for table, estimated in (
            ("verified_grams_per_unit", False),
            ("estimated_grams_per_unit", True),
        ):
            grams = curation.get(table, {}).get(f"{ingredient_id}|{unit}")
            if grams is not None:
                return quantity * Decimal(str(grams)), estimated, None

    return (
        None,
        False,
        f"quantité non convertible : {quantity} {unit} vers {base_unit}. "
        "Le fichier de curation ne porte pas d'équivalence pour "
        f"{ingredient_id} (densité, ou masse par {unit}).",
    )


def propose(url: str, page_bytes: bytes, seed_dir: Path) -> dict:
    """Le brouillon et ses propositions, sous une forme relisible et rejouable."""
    draft = extract_recipe(page_bytes, url)
    aliases = _aliases(seed_dir)
    catalogue = _catalogue(seed_dir)
    curation = json.loads(
        (ROOT / "config" / "cook_recipe_curation.json").read_text(encoding="utf-8")
    )

    lines = []
    for raw in draft.lines:
        parsed = parse_ingredient_line(raw)
        ingredient_id = resolve_canonical(parsed.label, aliases) if parsed.label else None
        canonical = catalogue.get(ingredient_id or "")
        blockers = []
        if parsed.quantity is None:
            blockers.append("aucune quantité lisible")
        if ingredient_id is None:
            blockers.append("aucun alias du canon ne nomme cet ingrédient")
        # La mesure de la bonne dimension d'abord : si la page publie les
        # grammes et que le canon pèse, il n'y a rien à convertir.
        chosen = (parsed.quantity, parsed.unit)
        if canonical is not None:
            wanted = _DIMENSION_OF_BASE_UNIT.get(canonical["base_unit"])
            # Métrique d'abord dans la bonne dimension : une cuillère est une
            # mesure publiée, mais sa taille dépend de l'ustensile.
            of_dimension = [
                (quantity, unit)
                for quantity, unit in parsed.candidates
                if dimension_of(unit) == wanted
            ]
            metric = [
                pair for pair in of_dimension
                if pair[1] in ("millilitre", "litre", "gram", "kilogram")
            ]
            if metric or of_dimension:
                chosen = (metric or of_dimension)[0]
        converted, estimated, blocker = (
            (None, False, None)
            if chosen[0] is None or canonical is None
            else _to_base_quantity(chosen[0], chosen[1], canonical, curation)
        )
        if blocker and not blockers:
            blockers.append(blocker)
        lines.append(
            {
                "original_ingredient_line": raw,
                "label": parsed.label,
                "parsed_numeric_quantity": (
                    None if chosen[0] is None else str(chosen[0])
                ),
                "normalized_unit": chosen[1],
                "published_measurements": [
                    f"{quantity} {unit}" for quantity, unit in parsed.candidates
                ],
                "proposed_canonical_ingredient_id": ingredient_id,
                "proposed_canonical_name": (
                    canonical["name"] if canonical is not None else None
                ),
                # `confirmed` est la seule chose qu'un humain écrit ici. Tant
                # qu'elle est `false`, `--apply` refuse la ligne : c'est ce qui
                # empêche une ressemblance de devenir une recette.
                "converted_base_quantity": None if converted is None else str(converted),
                "base_unit": canonical["base_unit"] if canonical is not None else None,
                "quantity_is_estimated": estimated,
                "confirmed": False,
                "blockers": blockers,
            }
        )
    return {
        "source_url": url,
        "name": draft.name,
        "servings": draft.servings,
        "prep_time_h": None if draft.prep_time_h is None else str(draft.prep_time_h),
        "cook_time_h": None if draft.cook_time_h is None else str(draft.cook_time_h),
        "lines": lines,
        "summary": {
            "lines": len(lines),
            "sans_blocage": sum(1 for line in lines if not line["blockers"]),
        },
    }


def build_recipe(review: dict) -> dict:
    """La recette, au contrat de `seed/main/recipes.json`.

    Exigences, toutes vérifiées avant d'écrire : chaque ligne est confirmée à la
    main, aucune ne porte de blocage, et le rendement est publié par la page. Une
    recette à moitié confirmée n'est pas une recette — c'est un chiffre inventé
    sur les portions qui manquent.
    """
    unconfirmed = [
        line["original_ingredient_line"]
        for line in review["lines"]
        if not line.get("confirmed") or line["blockers"]
    ]
    if unconfirmed:
        raise SystemExit(
            f"Refusé : {len(unconfirmed)} ligne(s) non confirmée(s) ou bloquée(s). "
            "Relire le fichier de revue, corriger ou retirer ces lignes, puis "
            "mettre \"confirmed\": true. Première : "
            f"{unconfirmed[0][:70]!r}"
        )
    if not review.get("servings"):
        raise SystemExit(
            "Refusé : la page ne publie pas de rendement. Une recette sans "
            "portions ne peut pas être mise à l'échelle, et en inventer un "
            "fausserait toutes ses quantités par portion."
        )
    servings = int(review["servings"])
    ingredients = []
    for line in review["lines"]:
        ingredients.append(
            {
                "canonical_ingredient_id": line["proposed_canonical_ingredient_id"],
                # Tout en composante fixe : la page décrit un lot pour le
                # rendement publié, et rien n'y dit ce qui varie par portion.
                # L'inventer serait une modélisation, pas une lecture.
                "qty_fixed_per_batch_base_unit": line["converted_base_quantity"],
                "qty_marginal_per_serving_base_unit": "0",
                "substitutable": False,
            }
        )
    return {
        "id": f"web_{_slug(review['name'])}",
        "name": review["name"],
        "original_servings": servings,
        "prep_time_fixed_h": review.get("prep_time_h") or "0",
        "prep_time_marginal_h": "0",
        "min_batch_servings": servings,
        "max_batch_servings": servings,
        "tags": {
            "import_origin": "web_url",
            "source_url": review["source_url"],
        },
        "required_equipment": [],
        "diet_flags": [],
        "allergen_flags": [],
        "ingredients": ingredients,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="page à lire")
    parser.add_argument(
        "--fixture", type=Path, help="page déjà enregistrée, au lieu du réseau"
    )
    parser.add_argument("--review", type=Path, help="fichier de revue à appliquer")
    parser.add_argument("--seed-dir", type=Path, default=ROOT / "seed" / "main")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="écrit la recette dans le seed — refuse si une ligne n'est pas confirmée",
    )
    args = parser.parse_args()

    if args.review is not None:
        review = json.loads(args.review.read_text(encoding="utf-8"))
        recipe = build_recipe(review)
        if not args.apply:
            print(json.dumps(recipe, ensure_ascii=False, indent=2))
            return 0
        path = args.seed_dir / "recipes.json"
        recipes = json.loads(path.read_text(encoding="utf-8"))
        if any(row["id"] == recipe["id"] for row in recipes):
            print(f"Refusé : {recipe['id']} est déjà dans le seed.", file=sys.stderr)
            return 1
        recipes.append(recipe)
        path.write_text(
            json.dumps(recipes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"{recipe['id']} ajoutée à {path} ({len(recipe['ingredients'])} lignes).")
        return 0

    if not args.url and not args.fixture:
        parser.error("donner --url, --fixture, ou --review")
    page = FixtureRecipePage(args.fixture) if args.fixture else UrlRecipePage()
    url = args.url or args.fixture.as_uri()
    try:
        review = propose(url, page.fetch(url), args.seed_dir)
    except ExtractionRefused as refusal:
        print(f"Refusé ({refusal.reason}) : {refusal}", file=sys.stderr)
        return 1

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    output = REVIEW_DIR / f"{_slug(review['name'])}.json"
    output.write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = review["summary"]
    print(
        f"{review['name']} — {review['servings']} portions, "
        f"{summary['sans_blocage']}/{summary['lines']} lignes sans blocage."
    )
    for line in review["lines"]:
        if line["blockers"]:
            print(f"   à revoir : {line['original_ingredient_line'][:56]!r}")
            for blocker in line["blockers"]:
                print(f"      {blocker}")
    print(f"\nFile de revue : {output}")
    print(
        "Confirmer chaque ligne (\"confirmed\": true), puis :\n"
        f"   python scripts/import_recipe_from_url.py --review {output} --apply"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
