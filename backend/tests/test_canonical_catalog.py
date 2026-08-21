"""Invariants du socle versionné d'ingrédients canoniques."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.ingestion.ingredient_curation import normalize_label

SEED = Path(__file__).resolve().parents[2] / "seed" / "main"

#: Le marché synthétique (produits, offres, bannières inventées) a quitté
#: `seed/main` avec D34 : ce répertoire est celui que `app.seeding.seed` charge
#: dans la base réelle, et les produits d'un magasin réel viennent du pipeline
#: de captures. `seed/demo` est donc le seul répertoire du dépôt qui porte
#: encore une liste de produits — c'est là que cet invariant va la lire.
DEMO = Path(__file__).resolve().parents[2] / "seed" / "demo"


def _load(name: str, directory: Path = SEED) -> list[dict]:
    return json.loads((directory / name).read_text(encoding="utf-8"))


def test_catalog_has_unique_purchasable_identities_and_valid_families():
    families = _load("ingredient_families.json")
    ingredients = _load("canonical_ingredients.json")
    family_ids = {row["id"] for row in families}
    ids = [row["id"] for row in ingredients]
    names = [normalize_label(row["name"]) for row in ingredients]

    assert len(families) >= 25
    assert len(ingredients) >= 1000
    assert len(ids) == len(set(ids))
    assert len(names) == len(set(names))
    assert all(re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", iid) for iid in ids)
    assert all(row["family_id"] in family_ids for row in ingredients)

    # L'existence du fichier est affirmée, pas testée : `seed/demo` est le seul
    # répertoire du dépôt qui porte encore une liste de produits, donc le seul
    # endroit où cet invariant peut vivre. Le mettre derrière un `if exists()`
    # le ferait disparaître sans un mot le jour où le fichier bouge.
    assert (DEMO / "products.json").exists(), (
        "seed/demo/products.json est le dernier porteur de la liste de "
        "produits : sans lui, l'invariant produit -> ingrédient canonique ne "
        "s'exerce plus nulle part."
    )
    product_ingredient_ids = {
        row["canonical_ingredient_id"]
        for row in _load("products.json", DEMO)
    }
    assert product_ingredient_ids <= set(ids)


def test_only_historical_solver_values_and_known_densities_are_populated():
    ingredients = _load("canonical_ingredients.json")
    calibrated = {
        row["id"] for row in ingredients if row["perishability"] is not None
    }
    salvage_calibrated = {
        row["id"]
        for row in ingredients
        if row["salvage_value_cents_per_base_unit"] is not None
    }
    assert len(calibrated) == 23
    assert salvage_calibrated == calibrated
    assert {
        "riz_basmati", "poulet_cuisse", "oeuf", "huile_olive"
    } <= calibrated
    densities = {
        row["id"]: row["density_g_per_ml"]
        for row in ingredients
        if row["density_g_per_ml"] is not None
    }
    # L'assertion est exhaustive exprès : une densité n'apparaît jamais sans
    # décision.
    assert densities == {
        # Écrites à la main avant l'import du FCÉN, sans provenance. Quatre
        # d'entre elles sont contredites de peu par la dérivation fédérale
        # (voir ci-dessous) : elles restent en place parce qu'elles portent
        # déjà des prix, et qu'un écart de 0,4 à 2,6 % ne vaut pas de les
        # déplacer.
        "bouillon_poulet": 1.0,
        "creme_35": 0.98,
        "eau": 1.0,
        "huile_olive": 0.91,
        "lait_325": 1.03,
        "sauce_soja": 1.1,
        # Dérivées des mesures de service fédérales (type 6) par
        # scripts/derive_fcen_measures.py, chacune avec sa provenance en
        # commentaire dans scripts/catalog_seed_data.py.
        "aromatisant_eau": 1.014,
        "babeurre": 1.036,
        "biere_blonde": 1.004,
        "cidre_pomme": 1.0,
        "creme_15": 1.014,
        "huile_canola": 0.921,
        "huile_non_precisee": 0.921,
        "huile_sesame_grillee": 0.921,
        "huile_vegetale": 0.921,
        "ketchup": 1.014,
        "lait_evapore": 1.065,
        "lait_non_precise": 1.031,
        "lait_soya": 1.042,
        "mayonnaise": 0.93,
        "melasse": 1.424,
        "miel": 1.432,
        "moutarde_ancienne": 1.04,
        "moutarde_dijon": 1.04,
        "moutarde_jaune": 1.053,
        "moutarde_non_precisee": 1.053,
        "relish": 1.036,
        "salsa": 1.095,
        "sambal_oelek": 1.014,
        "sauce_chili": 1.154,
        "sauce_hoisin": 1.081,
        "sauce_piquante": 0.959,
        "sauce_poisson": 1.216,
        "sauce_tabasco": 0.959,
        "sauce_tomate": 1.036,
        "sauce_worcestershire": 1.162,
        "sirop_erable": 1.331,
        "sriracha": 1.327,
        "toum": 0.93,
        "vin_blanc_sec": 0.994,
        "vin_rouge_sec": 0.994,
        "vinaigre_balsamique": 1.078,
        "vinaigre_blanc": 1.014,
        "vinaigre_cidre": 1.014,
        "vinaigre_riz": 1.014,
        "vinaigre_vin_rouge": 1.01,
    }
    # Les quatre valeurs à la main que la dérivation contredit, nommées ici
    # pour qu'un désaccord connu ne se lise pas comme un accord :
    #   creme_35 : seed 0.98, FCÉN 1.006
    #   huile_olive : seed 0.91, FCÉN 0.913
    #   lait_325 : seed 1.03, FCÉN 1.031
    #   sauce_soja : seed 1.1, FCÉN 1.078


def test_aliases_are_bilingual_deterministic_and_point_to_the_catalog():
    ingredients = _load("canonical_ingredients.json")
    aliases = _load("canonical_ingredient_aliases.json")
    ingredient_ids = {row["id"] for row in ingredients}
    keys = [
        (row["language"], row["normalized_alias"])
        for row in aliases
    ]

    assert {row["language"] for row in aliases} == {"en", "fr"}
    assert len(keys) == len(set(keys))
    assert all(row["canonical_ingredient_id"] in ingredient_ids for row in aliases)
    assert all(
        row["normalized_alias"] == normalize_label(row["alias"])
        for row in aliases
    )
    english_targets = {
        row["canonical_ingredient_id"]
        for row in aliases
        if row["language"] == "en"
    }
    assert english_targets == ingredient_ids

    owners_by_label: dict[str, set[str]] = {}
    for ingredient in ingredients:
        owners_by_label.setdefault(
            normalize_label(ingredient["name"]), set()
        ).add(ingredient["id"])
    for alias in aliases:
        owners_by_label.setdefault(alias["normalized_alias"], set()).add(
            alias["canonical_ingredient_id"]
        )
    assert all(len(owners) == 1 for owners in owners_by_label.values())
