"""Convertit le corpus français de Cook vers le contrat JSON de Souschef.

Les recettes complètes et non sucrées sont écrites dans
``seed/main/imported_recipes.json`` et fusionnées dans
``seed/main/recipes.json``. Les recettes incomplètes sont conservées au même
format dans une file de révision; les desserts sont archivés séparément et
aucune valeur inconnue n'est remplacée par zéro.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    ROOT.parent.parent
    / "Cook"
    / "data"
    / "recipe_sources"
    / "french_recipe_corpus_200.json"
)
IMPORTED_PATH = ROOT / "seed" / "main" / "imported_recipes.json"
RECIPES_PATH = ROOT / "seed" / "main" / "recipes.json"
REVIEW_PATH = (
    ROOT / "data" / "recipe-import-review" / "cook-recipes-review.json"
)
EXCLUDED_PATH = (
    ROOT / "data" / "recipe-import-review" / "cook-recipes-excluded.json"
)
REPORT_PATH = (
    ROOT / "data" / "recipe-import-review" / "cook-recipes-import-report.json"
)
CANONICAL_PATH = ROOT / "seed" / "main" / "canonical_ingredients.json"
CURATION_PATH = ROOT / "config" / "cook_recipe_curation.json"
_SOURCE_PREFIXES = {
    "ricardo": "ricardo",
    "bon_pour_toi": "bon_pour_toi",
    "la_cuisine_de_jean_philippe": "jean_philippe",
}
_IMPORT_ORIGIN = "cook_french_recipe_corpus"
_DESSERT_CATEGORIES = {"desserts", "glacages et coulis"}
_DESSERT_SOURCE_URLS = {
    "https://www.lacuisinedejeanphilippe.com/recipe/chausson-la-pomme",
    "https://www.lacuisinedejeanphilippe.com/recipe/crepes-vegan",
    "https://www.lacuisinedejeanphilippe.com/recipe/crumble-amandes-et-bleuets-vegan",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()

    source_path = args.source.resolve()
    corpus = json.loads(source_path.read_text(encoding="utf-8"))
    canonical_rows = json.loads(CANONICAL_PATH.read_text(encoding="utf-8"))
    canonical_catalog = {row["id"]: row for row in canonical_rows}
    curation = json.loads(CURATION_PATH.read_text(encoding="utf-8"))
    imported, review, excluded, report = convert_corpus(
        corpus,
        set(canonical_catalog),
        canonical_catalog=canonical_catalog,
        curation=curation,
    )

    current = json.loads(RECIPES_PATH.read_text(encoding="utf-8"))
    generated = [
        recipe
        for recipe in current
        if recipe.get("tags", {}).get("import_origin") != _IMPORT_ORIGIN
    ]
    duplicate_ids = {row["id"] for row in generated} & {
        row["id"] for row in imported
    }
    if duplicate_ids:
        raise ValueError(
            f"Identifiants déjà présents dans recipes.json: {sorted(duplicate_ids)}"
        )

    _write_json(IMPORTED_PATH, imported)
    _write_json(RECIPES_PATH, generated + imported)
    _write_json(REVIEW_PATH, review)
    _write_json(EXCLUDED_PATH, excluded)
    _write_json(
        REPORT_PATH,
        {
            **report,
            "source_path": str(source_path),
            "active_recipe_total": len(generated) + len(imported),
            "preexisting_recipes": len(generated),
            "imported_recipes_path": str(IMPORTED_PATH),
            "review_path": str(REVIEW_PATH),
            "excluded_path": str(EXCLUDED_PATH),
        },
    )
    print(
        f"Cook vers Souschef : {len(imported)} recettes actives, "
        f"{len(review)} à réviser, {len(excluded)} desserts exclus; "
        f"{len(generated) + len(imported)} recettes "
        "dans seed/main/recipes.json."
    )
    return 0


def convert_corpus(
    corpus: dict,
    canonical_ids: set[str],
    *,
    canonical_catalog: dict[str, dict] | None = None,
    curation: dict | None = None,
) -> tuple[list[dict], list[dict], list[dict], dict]:
    canonical_catalog = canonical_catalog or {}
    curation = curation or {}
    imported: list[dict] = []
    review: list[dict] = []
    excluded: list[dict] = []
    seen_ids: set[str] = set()
    source_counts: dict[str, dict[str, int]] = {}
    unknown_canonical_ids: set[str] = set()

    for source_recipe in corpus.get("recipes", []):
        recipe = _convert_recipe(source_recipe, canonical_catalog, curation)
        if recipe["id"] in seen_ids:
            raise ValueError(f"Identifiant de recette dupliqué: {recipe['id']}")
        seen_ids.add(recipe["id"])

        source = str(source_recipe.get("source") or "unknown")
        counts = source_counts.setdefault(source, {"ready": 0, "review": 0})
        dessert_reason = _dessert_reason(source_recipe)
        if dessert_reason is not None:
            recipe["tags"]["import_status"] = "excluded"
            recipe["tags"]["exclusion_reason"] = dessert_reason
            excluded.append(recipe)
            counts["excluded"] = counts.get("excluded", 0) + 1
            continue
        ingredient_ids = {
            ingredient["canonical_ingredient_id"]
            for ingredient in recipe["ingredients"]
            if ingredient["canonical_ingredient_id"]
        }
        unknown_canonical_ids.update(ingredient_ids - canonical_ids)
        complete = _is_complete(recipe) and not (ingredient_ids - canonical_ids)
        if complete:
            if source_recipe.get("import_status") != "READY":
                recipe["tags"]["import_status"] = "curated"
            imported.append(recipe)
            counts["ready"] += 1
        else:
            review.append(recipe)
            counts["review"] += 1

    imported.sort(key=lambda row: row["id"])
    review.sort(key=lambda row: row["id"])
    excluded.sort(key=lambda row: row["id"])
    return imported, review, excluded, {
        "source_selected": int(corpus.get("summary", {}).get("selected", 0)),
        "source_retained": len(corpus.get("recipes", [])),
        "imported_ready": len(imported),
        "review_required": len(review),
        "desserts_excluded": len(excluded),
        "by_source": dict(sorted(source_counts.items())),
        "unknown_canonical_ids": sorted(unknown_canonical_ids),
    }


def _dessert_reason(source_recipe: dict) -> str | None:
    categories = {
        _slug(value)
        for value in (source_recipe.get("tags") or {}).get("categories", [])
    }
    dessert_categories = {_slug(value) for value in _DESSERT_CATEGORIES}
    matched = sorted(categories & dessert_categories)
    if matched:
        return f"dessert_category:{matched[0]}"
    if str(source_recipe.get("source_url") or "").rstrip("/") in {
        value.rstrip("/") for value in _DESSERT_SOURCE_URLS
    }:
        return "curated_dessert_url"
    return None


def _convert_recipe(
    source_recipe: dict,
    canonical_catalog: dict[str, dict] | None = None,
    curation: dict | None = None,
) -> dict:
    canonical_catalog = canonical_catalog or {}
    curation = curation or {}
    projection = source_recipe.get("souschef_projection") or {}
    source = str(source_recipe.get("source") or "unknown")
    source_url = str(source_recipe.get("source_url") or "")
    tags = dict(projection.get("tags") or source_recipe.get("tags") or {})
    tags.update(
        {
            "source": source,
            "source_url": source_url,
            "import_origin": _IMPORT_ORIGIN,
            "import_status": str(
                source_recipe.get("import_status") or "REVIEW_REQUIRED"
            ).casefold(),
        }
    )
    if source_recipe.get("review_flags"):
        tags["review_flags"] = source_recipe["review_flags"]

    raw_by_identity = {
        row.get("ingredient_identity_id"): row
        for row in source_recipe.get("ingredients", [])
        if row.get("ingredient_identity_id")
    }
    mappings = curation.get("identity_mappings", {})
    ingredients = []
    omissions = []
    estimates = []
    for ingredient in projection.get("ingredients", []):
        identity = ingredient.get("ingredient_identity_id")
        raw = raw_by_identity.get(identity)
        explicitly_mapped = identity in mappings
        canonical_id = (
            mappings.get(identity)
            if explicitly_mapped
            else ingredient.get("canonical_ingredient_id")
        )
        if explicitly_mapped and canonical_id is None:
            omissions.append(_omission_row(identity, raw, "curated_non_solver_item"))
            continue

        if raw is not None and canonical_id:
            override_key = f"{canonical_id}|{raw.get('normalized_unit')}"
            canonical_id = curation.get("canonical_overrides", {}).get(
                override_key, canonical_id
            )

        fixed = ingredient.get("qty_fixed_per_batch_base_unit")
        marginal = ingredient.get("qty_marginal_per_serving_base_unit")
        needs_resolution = explicitly_mapped or fixed is None or marginal is None
        # La projection amont recopie parfois le compte d'articles de la ligne
        # source (« 1 aubergine ») dans un champ exprimé en grammes : la
        # recette demande alors 1 g d'aubergine, ce qu'aucune étape ultérieure
        # ne peut plus détecter. Un compte n'est une quantité que si le
        # canonique se compte lui aussi. Sinon on repasse par la résolution,
        # qui sait lire « boîte de 796 ml » dans la ligne ou appliquer une
        # équivalence curée.
        if (
            not needs_resolution
            and raw is not None
            and canonical_id
            and _count_copied_into_measured_field(
                raw, fixed, canonical_id, canonical_catalog
            )
        ):
            needs_resolution = True
        if needs_resolution and raw is not None and canonical_id:
            fixed, basis, estimated = _resolve_quantity(
                raw,
                ingredient,
                canonical_id,
                canonical_catalog,
                curation,
            )
            marginal = "0" if fixed is not None else None
            if fixed is None and _should_omit_unquantified(raw):
                omissions.append(
                    _omission_row(identity, raw, "unquantified_non_solver_item")
                )
                continue
            if estimated:
                estimates.append(
                    {
                        "ingredient_identity_id": identity,
                        "ingredient_line": raw.get("original_ingredient_line"),
                        "basis": basis,
                    }
                )
        ingredients.append(
            {
                "canonical_ingredient_id": canonical_id,
                "qty_fixed_per_batch_base_unit": fixed,
                "qty_marginal_per_serving_base_unit": marginal,
                "substitutable": bool(ingredient.get("substitutable", False)),
            }
        )

    ingredients, merged_lines = _merge_duplicate_ingredients(ingredients)
    if merged_lines:
        tags["merged_duplicate_ingredients"] = merged_lines
    if omissions:
        tags["solver_omissions"] = omissions
    if estimates:
        tags["quantity_estimates"] = estimates

    source_url_key = source_url.rstrip("/")
    serving_override = curation.get("serving_overrides", {}).get(source_url_key)
    original_servings = projection.get("original_servings")
    # Le rendement publié par la source voyage avec la recette : « 20
    # boulettes » ou « 625 ml » ne sont pas des portions, et sans cette
    # preuve rien en aval ne peut distinguer une grosse recette d'un
    # rendement mal lu.
    servings_source = source_recipe.get("servings_source")
    if servings_source is not None:
        tags["servings_source"] = str(servings_source)
    if serving_override is not None:
        original_servings = serving_override
        tags["servings_basis"] = "curated_from_recipe_yield_and_instructions"

    return {
        "id": _recipe_id(source, source_url, source_recipe.get("title")),
        "name": projection.get("name") or source_recipe.get("title") or "",
        "original_servings": original_servings,
        "prep_time_fixed_h": _number_text(projection.get("prep_time_fixed_h")),
        "prep_time_marginal_h": _number_text(
            projection.get("prep_time_marginal_h")
        ),
        "min_batch_servings": projection.get("min_batch_servings"),
        "max_batch_servings": projection.get("max_batch_servings"),
        "tags": tags,
        "required_equipment": list(projection.get("required_equipment") or []),
        "diet_flags": list(projection.get("diet_flags") or []),
        "allergen_flags": list(projection.get("allergen_flags") or []),
        "ingredients": ingredients,
    }


def _merge_duplicate_ingredients(
    rows: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Additionne les lignes d'un même ingrédient. Un plat n'en a qu'un besoin.

    `catalog.recipe_ingredient` impose l'unicité de (recette, ingrédient) et le
    seeding fait un upsert : deux lignes pour le même ingrédient — cas très
    courant, la marinade puis la sauce — laissaient la dernière **écraser** les
    précédentes en base, pendant que le calcul de prix sur le JSON les
    additionnait. Deux réponses pour une même recette, selon le chemin. La
    somme est faite ici, une seule fois, et la trace des lignes fusionnées
    reste dans les tags.
    """
    result: list[dict] = []
    position: dict[str, int] = {}
    counts: dict[str, int] = {}
    for row in rows:
        key = row.get("canonical_ingredient_id")
        if key is None or key not in position:
            if key is not None:
                position[key] = len(result)
                counts[key] = 1
            result.append(dict(row))
            continue
        counts[key] += 1
        target = result[position[key]]
        for field in (
            "qty_fixed_per_batch_base_unit",
            "qty_marginal_per_serving_base_unit",
        ):
            left = _decimal(target.get(field))
            right = _decimal(row.get(field))
            if left is None or right is None:
                # Une quantité inconnue ne s'additionne pas : on garde celle
                # qui existe plutôt que d'inventer un total.
                target[field] = row.get(field) if left is None else target.get(field)
            else:
                target[field] = _decimal_text(left + right)
        target["substitutable"] = bool(target.get("substitutable")) and bool(
            row.get("substitutable")
        )
    merged = [
        {
            "canonical_ingredient_id": key,
            "merged_lines": counts[key],
            "qty_fixed_per_batch_base_unit": result[position[key]][
                "qty_fixed_per_batch_base_unit"
            ],
        }
        for key in position
        if counts[key] > 1
    ]
    return result, merged


#: Unités de la source qui dénombrent des articles au lieu de les mesurer.
_COUNT_UNITS = {
    "piece", "unit", "clove", "slice", "stalk", "head", "bunch", "sprig",
    "leaf", "can", "package", "pinch",
}


def _count_copied_into_measured_field(
    raw: dict,
    fixed: object,
    canonical_id: str,
    canonical_catalog: dict[str, dict],
) -> bool:
    """La quantité projetée est-elle un compte d'articles déguisé en mesure ?"""
    canonical = canonical_catalog.get(canonical_id) or {}
    if canonical.get("base_unit") not in {"g", "ml"}:
        return False
    if raw.get("normalized_unit") not in _COUNT_UNITS:
        return False
    count = _decimal(raw.get("parsed_numeric_quantity"))
    projected = _decimal(fixed)
    return count is not None and projected is not None and count == projected


def _resolve_quantity(
    raw: dict,
    projected: dict,
    canonical_id: str,
    canonical_catalog: dict[str, dict],
    curation: dict,
) -> tuple[str | None, str | None, bool]:
    identity = raw.get("ingredient_identity_id")
    override = curation.get("quantity_overrides", {}).get(identity)
    if override is not None:
        return _decimal_text(Decimal(str(override["quantity"]))), override["basis"], True

    canonical = canonical_catalog.get(canonical_id) or {}
    base_unit = canonical.get("base_unit")
    raw_unit = raw.get("normalized_unit")
    quantity = _decimal(raw.get("parsed_numeric_quantity"))
    projected_quantity = _decimal(projected.get("qty_fixed_per_batch_base_unit"))

    if base_unit == "unit" and quantity is not None and raw_unit in {
        "clove", "piece", "slice", "stalk", "unit",
    }:
        return _decimal_text(quantity), "declared count in compatible base unit", False

    secondary = _converted_quantity(
        raw.get("secondary_quantity"), raw.get("secondary_unit"), base_unit
    )
    if secondary is not None:
        return _decimal_text(secondary), "explicit secondary quantity", False

    line = str(raw.get("original_ingredient_line") or "")
    explicit = _explicit_quantity_from_line(line, base_unit, quantity, raw_unit)
    if explicit is not None:
        return _decimal_text(explicit), "explicit package mass or volume", False

    direct = _converted_quantity(quantity, raw_unit, base_unit)
    if direct is not None:
        return _decimal_text(direct), "declared quantity in compatible dimension", False

    secondary_volume = _volume_ml(
        _decimal(raw.get("secondary_quantity")), raw.get("secondary_unit")
    )
    explicit_volume = _explicit_quantity_from_line(
        line, "ml", quantity, raw_unit
    )
    volume_ml = secondary_volume or explicit_volume or _volume_ml(quantity, raw_unit)
    if volume_ml is None and raw_unit in {"cup", "tablespoon", "teaspoon"}:
        volume_ml = projected_quantity
    if volume_ml is None and base_unit == "ml" and projected_quantity is not None:
        volume_ml = projected_quantity
    if volume_ml is not None and base_unit == "g":
        density = curation.get("grams_per_millilitre", {}).get(canonical_id)
        if density is not None:
            return (
                _decimal_text(volume_ml * Decimal(str(density))),
                f"curated density {density} g/ml",
                canonical_id not in {"cassonade", "origan_seche", "thym_frais"},
            )
    if volume_ml is not None and base_unit == "ml":
        return _decimal_text(volume_ml), "declared volume", False

    count_unit = raw_unit or "unit"
    count_key = f"{canonical_id}|{count_unit}"
    if quantity is not None:
        verified = curation.get("verified_grams_per_unit", {}).get(count_key)
        if verified is not None and base_unit == "g":
            return (
                _decimal_text(quantity * Decimal(str(verified))),
                f"verified equivalence {verified} g/{count_unit}",
                False,
            )
        estimated = curation.get("estimated_grams_per_unit", {}).get(count_key)
        if estimated is not None and base_unit == "g":
            return (
                _decimal_text(quantity * Decimal(str(estimated))),
                f"declared estimate {estimated} g/{count_unit}",
                True,
            )

    return None, None, False


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", ".")
    try:
        if "/" in text:
            return Decimal(Fraction(text).numerator) / Decimal(Fraction(text).denominator)
        return Decimal(text)
    except (InvalidOperation, ValueError, ZeroDivisionError):
        return None


def _mass_g(quantity: Decimal | None, unit: object) -> Decimal | None:
    if quantity is None:
        return None
    factors = {
        "gram": Decimal("1"),
        "kilogram": Decimal("1000"),
        "ounce": Decimal("28.349523125"),
        "pound": Decimal("453.59237"),
    }
    factor = factors.get(str(unit))
    return None if factor is None else quantity * factor


def _volume_ml(quantity: Decimal | None, unit: object) -> Decimal | None:
    if quantity is None:
        return None
    factors = {
        "millilitre": Decimal("1"),
        "litre": Decimal("1000"),
        "cup": Decimal("250"),
        "tablespoon": Decimal("15"),
        "teaspoon": Decimal("5"),
    }
    factor = factors.get(str(unit))
    return None if factor is None else quantity * factor


def _converted_quantity(
    quantity_value: object, unit: object, base_unit: object
) -> Decimal | None:
    quantity = _decimal(quantity_value)
    if base_unit == "g":
        return _mass_g(quantity, unit)
    if base_unit == "ml":
        return _volume_ml(quantity, unit)
    return None


def _explicit_quantity_from_line(
    line: str,
    base_unit: object,
    count: Decimal | None,
    raw_unit: object,
) -> Decimal | None:
    unit_pattern = r"kg|g|ml|l"
    matches = re.findall(rf"(?<![\d/])(\d+(?:[,.]\d+)?)\s*({unit_pattern})\b", line.casefold())
    converted = []
    for number, unit in matches:
        normalized_unit = {"kg": "kilogram", "g": "gram", "ml": "millilitre", "l": "litre"}[unit]
        value = _converted_quantity(number, normalized_unit, base_unit)
        if value is not None:
            converted.append(value)
    if not converted:
        return None
    value = converted[-1]
    package_line = _slug(line)
    if (
        raw_unit in {"can", "package"}
        or any(marker in package_line for marker in ("boite", "conserve", "paquet"))
    ) and count is not None and count > 1:
        value *= count
    return value


def _should_omit_unquantified(raw: dict) -> bool:
    line = _slug(raw.get("original_ingredient_line"))
    return bool(
        raw.get("optional_or_for_serving")
        or not line
        or line.endswith("riz")
        or any(
            marker in line
            for marker in (
                "au_gout",
                "facultatif",
                "pour_le_service",
                "pour_garnir",
                "en_quantite_suffisante",
                "pour_huiler",
                "soupcon",
            )
        )
        or line in {
            "coriandre_fraiche",
            "eau",
            "sel",
            "poivre",
            "sel_et_poivre",
            "poivre_noir_moulu",
        }
    )


def _omission_row(identity: object, raw: dict | None, reason: str) -> dict:
    return {
        "ingredient_identity_id": identity,
        "ingredient_line": None if raw is None else raw.get("original_ingredient_line"),
        "reason": reason,
    }


def _decimal_text(value: Decimal) -> str:
    normalized = format(value.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized


def _is_complete(recipe: dict) -> bool:
    required = (
        "id",
        "name",
        "original_servings",
        "prep_time_fixed_h",
        "prep_time_marginal_h",
        "min_batch_servings",
        "max_batch_servings",
    )
    if any(recipe.get(field) in (None, "") for field in required):
        return False
    if not recipe["ingredients"]:
        return False
    return all(
        ingredient["canonical_ingredient_id"]
        and ingredient["qty_fixed_per_batch_base_unit"] is not None
        and ingredient["qty_marginal_per_serving_base_unit"] is not None
        for ingredient in recipe["ingredients"]
    )


def _recipe_id(source: str, source_url: str, title: object) -> str:
    prefix = _SOURCE_PREFIXES.get(source, _slug(source) or "source")
    path = unquote(urlsplit(source_url).path).rstrip("/")
    source_slug = path.rsplit("/", 1)[-1] if path else str(title or "recette")
    candidate = f"{prefix}_{_slug(source_slug)}".strip("_")
    if len(candidate) <= 64:
        return candidate
    digest = sha256(source_url.encode("utf-8")).hexdigest()[:10]
    return f"{candidate[:53].rstrip('_')}_{digest}"


def _slug(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_")


def _number_text(value: object) -> str | None:
    return None if value is None else str(value)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
