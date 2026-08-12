"""Seeding idempotent depuis les fichiers JSON versionnés de ``seed/``.

Aucune donnée en dur dans le code : tout provient des fichiers JSON. Le
seeding est rejouable — chaque exécution converge vers le même état
(upserts par clés naturelles, offres dédupliquées par empreinte).

Cheminement des PRIX : ils ne sont jamais insérés directement dans
``market.price``. Ils passent par le :class:`CircularPort` (adaptateur JSON),
atterrissent en ``staging.raw_offer``, puis sont normalisés — exactement le
chemin qu'empruntera le vrai scraper (docs/spec.md, « Ports à définir »).

Usage : ``python -m app.seeding.seed [--seed-dir seed/main]``
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..adapters import JsonCircularAdapter, JsonRecipeSourceAdapter
from ..db import SessionLocal
from ..ingestion.normalize import land_offers, normalize_offers
from ..models import (
    CanonicalIngredient,
    CanonicalIngredientAlias,
    CanonicalIngredientExternalRef,
    HouseholdMember,
    HouseholdProfile,
    IngredientCurationEvent,
    IngredientFamily,
    Product,
    Recipe,
    RecipeIngredient,
    Staple,
    Store,
)
from ..services.dish_family import dish_family_id_of


def _upsert(session: Session, model, rows: list[dict], key_cols: list[str]) -> int:
    """Upsert générique par clés naturelles ; retourne le nombre de lignes traitées."""
    for row in rows:
        stmt = pg_insert(model).values(**row)
        update_cols = {k: v for k, v in row.items() if k not in key_cols}
        if update_cols:
            stmt = stmt.on_conflict_do_update(
                index_elements=key_cols, set_=update_cols
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=key_cols)
        session.execute(stmt)
    return len(rows)


def _load(seed_dir: Path, name: str) -> list | dict:
    return json.loads((seed_dir / name).read_text())


def _load_optional(seed_dir: Path, name: str) -> list:
    path = seed_dir / name
    return json.loads(path.read_text()) if path.exists() else []


def seed_catalog(
    session: Session, seed_dir: Path, recipe_source=None
) -> None:
    families = _load(seed_dir, "ingredient_families.json")
    n = _upsert(session, IngredientFamily, families, ["id"])
    print(f"  catalog.ingredient_family    : {n} lignes")

    ingredients = _load(seed_dir, "canonical_ingredients.json")
    n = _upsert(session, CanonicalIngredient, ingredients, ["id"])
    print(f"  catalog.canonical_ingredient : {n} lignes")

    aliases = _load(seed_dir, "canonical_ingredient_aliases.json")
    n = _upsert(
        session,
        CanonicalIngredientAlias,
        aliases,
        ["language", "normalized_alias"],
    )
    print(f"  catalog.ingredient_alias     : {n} lignes")

    external_refs = _load_optional(
        seed_dir, "canonical_ingredient_external_refs.json"
    )
    n = _upsert(
        session,
        CanonicalIngredientExternalRef,
        external_refs,
        ["source", "external_id", "source_version"],
    )
    print(f"  catalog.ingredient_ref       : {n} lignes")

    curation_events = _load_optional(seed_dir, "ingredient_curation_events.json")
    n = _upsert(
        session,
        IngredientCurationEvent,
        curation_events,
        ["decision_fingerprint"],
    )
    print(f"  catalog.curation_event       : {n} lignes")

    # Recettes via le port (injectable) — même contrat que le futur catalogue.
    recipes = (recipe_source or JsonRecipeSourceAdapter(seed_dir)).load_all()
    recipe_rows, ri_rows = [], []
    for r in recipes:
        d = r.model_dump()
        ings = d.pop("ingredients")
        d["dish_family_id"] = dish_family_id_of(d["id"])
        recipe_rows.append(d)
        for ing in ings:
            ri_rows.append({"recipe_id": r.id, **ing})
    n = _upsert(session, Recipe, recipe_rows, ["id"])
    print(f"  catalog.recipe               : {n} lignes")
    n = _upsert(
        session, RecipeIngredient, ri_rows, ["recipe_id", "canonical_ingredient_id"]
    )
    print(f"  catalog.recipe_ingredient    : {n} lignes")


def seed_market_static(session: Session, seed_dir: Path) -> None:
    # market : clés de substitution ; l'idempotence passe par external_key.
    n = _upsert(session, Store, _load(seed_dir, "stores.json"), ["external_key"])
    print(f"  market.store                 : {n} lignes")
    n = _upsert(session, Product, _load(seed_dir, "products.json"), ["external_key"])
    print(f"  market.product               : {n} lignes")


def seed_prices_via_ingestion(
    session: Session, seed_dir: Path, circular=None
) -> None:
    """Prix : port (injectable) → staging → normalisation (jamais d'insertion
    directe)."""
    port = circular or JsonCircularAdapter(seed_dir)
    landed = 0
    for store_key in port.all_store_keys():
        for week in port.all_weeks():
            landed += land_offers(session, port, store_key, week)
    stats = normalize_offers(session)
    print(f"  staging.raw_offer            : {landed} nouvelles offres")
    print(
        f"  market.price (normalisation) : {stats['prices_upserted']} upserts,"
        f" {stats['unmapped']} non mappées"
    )


def seed_household(session: Session, seed_dir: Path) -> None:
    data = _load(seed_dir, "household.json")
    profile = dict(data["profile"])
    members = data["members"]
    staples = data["staples"]
    profile["max_share_per_recipe"] = Decimal(str(profile["max_share_per_recipe"]))
    _upsert(session, HouseholdProfile, [profile], ["id"])
    _upsert(
        session,
        HouseholdMember,
        [{"household_profile_id": profile["id"], **m} for m in members],
        ["household_profile_id", "name"],
    )
    _upsert(
        session,
        Staple,
        [
            {"household_profile_id": profile["id"], "canonical_ingredient_id": iid}
            for iid in staples
        ],
        ["household_profile_id", "canonical_ingredient_id"],
    )
    print(
        f"  household                    : 1 profil, {len(members)} membres,"
        f" {len(staples)} essentiels"
    )


def run(
    seed_dir: str,
    session_factory=SessionLocal,
    recipe_source=None,
    circular=None,
) -> None:
    """Ports et fabrique de session injectables : le vrai scraper (ou un
    faux de test) se branche ici sans toucher au pipeline."""
    path = Path(seed_dir)
    print(f"Seeding depuis {path} …")
    with session_factory() as session:
        seed_catalog(session, path, recipe_source=recipe_source)
        seed_market_static(session, path)
        seed_prices_via_ingestion(session, path, circular=circular)
        seed_household(session, path)
        session.commit()
    print("Seeding terminé (idempotent : rejouable sans effet de bord).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-dir", default=None)
    args = parser.parse_args()
    from ..config import settings

    run(args.seed_dir or settings.seed_dir)
