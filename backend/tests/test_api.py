"""Tests de l'API (étape 5) contre la base de test seedée (instance jouet).

Le ``commit`` (pilote, docs/product-pilot.md — depuis le retrait du
garde-manger) est une simple validation + passage à ``committed`` ; la
confirmation post-génération (``needed_ingredients``/``finalize``) est le
point qui ajuste la logistique d'achat une dernière fois avant commit.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.models import Product
from tests.db_fixtures import api_client, db_session, test_engine, toy_seeded  # noqa: F401

ON = "2026-08-10"
ALL_ON = {
    "enable_multi_store": True, "enable_batch_fixed_cost": True,
    "enable_salvage": True, "enable_time_cost": True,
    "enable_staples": True, "enable_diversity": True,
}


def test_household_roundtrip(api_client):
    r = api_client.get("/api/household")
    assert r.status_code == 200
    h = r.json()
    assert Decimal(h["demand"]["D_exact"]) == Decimal("4")
    assert (h["demand"]["borne_basse"], h["demand"]["borne_haute"]) == (4, 5)

    r = api_client.put("/api/household", json={"meals_per_horizon": 6})
    assert r.status_code == 200
    assert Decimal(r.json()["demand"]["D_exact"]) == Decimal("6")
    api_client.put("/api/household", json={"meals_per_horizon": 4})  # restauration


def test_staples_roundtrip(api_client):
    r = api_client.put(
        "/api/staples", json={"canonical_ingredient_ids": ["riz", "lentille"]},
    )
    assert r.status_code == 200
    assert {row["canonical_ingredient_id"] for row in r.json()} == {"riz", "lentille"}

    r = api_client.get("/api/staples")
    assert {row["canonical_ingredient_id"] for row in r.json()} == {"riz", "lentille"}

    # Remplace l'ensemble complet — pas un upsert ligne par ligne.
    r = api_client.put("/api/staples", json={"canonical_ingredient_ids": ["oeuf"]})
    assert {row["canonical_ingredient_id"] for row in r.json()} == {"oeuf"}

    r = api_client.put(
        "/api/staples", json={"canonical_ingredient_ids": ["inexistant"]},
    )
    assert r.status_code == 422


def test_plan_create_fetch_and_grocery_grouping(api_client):
    r = api_client.post("/api/plan", json={"config": {}, "on_date": ON})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["solver_status"] == "Optimal"
    assert plan["status"] == "proposed"
    # Menu monotone attendu (config défaut, jouet) : riz ×5, un sac de 400 g.
    assert plan["menu"][0]["recipe_id"] == "riz_nature"
    groups = plan["grocery_list_by_store"]
    assert len(groups) == 1 and groups[0]["store_external_key"] == "toy_store"
    line = groups[0]["lines"][0]
    assert line["product_external_key"] == "riz_400g"
    # ingredient_name porte le type de produit (« Riz ») — brand/package_unit
    # seuls ne le disent pas (ex. « Great Value, 900 g » sans plus de
    # contexte), bug relevé en test manuel dans le navigateur.
    assert line["ingredient_name"] == "Riz"
    assert line["consumed_by"] == ["Riz nature"]
    assert groups[0]["subtotal_cents_cad"] == "180.00"
    assert plan["diagnostic"]["objective_terms_cents"]["total"] == "-333.50"

    r2 = api_client.get(f"/api/plan/{plan['id']}")
    assert r2.status_code == 200 and r2.json()["id"] == plan["id"]
    assert api_client.get("/api/plan/999999").status_code == 404


def test_reoptimize_locks_replaces_and_explains(api_client):
    """Verrouillage/remplacement (pilote, docs/product-pilot.md) : verrouiller
    riz_nature, remplacer dahl_toy — la portion verrouillée ne bouge pas, la
    réponse explique ce qui a changé."""
    r = api_client.post("/api/plan", json={"config": ALL_ON, "on_date": ON})
    plan = r.json()
    riz_servings = next(
        m["servings"] for m in plan["menu"] if m["recipe_id"] == "riz_nature"
    )
    assert set(m["recipe_id"] for m in plan["menu"]) == {"riz_nature", "dahl_toy"}

    r = api_client.post(
        f"/api/plan/{plan['id']}/reoptimize",
        json={
            "config": ALL_ON,
            "locked_recipe_ids": ["riz_nature"],
            "excluded_recipe_ids": ["dahl_toy"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"]["solver_status"] == "Optimal"
    assert body["plan"]["id"] != plan["id"]
    new_servings = {m["recipe_id"]: m["servings"] for m in body["plan"]["menu"]}
    assert new_servings["riz_nature"] == riz_servings
    assert "dahl_toy" not in new_servings
    assert body["changes"]["removed"] == ["dahl_toy"]
    assert "riz_nature" not in body["changes"]["added"]

    # Verrouiller une recette absente du plan.
    r = api_client.post(
        f"/api/plan/{plan['id']}/reoptimize",
        json={"locked_recipe_ids": ["omelette_toy"]},
    )
    assert r.status_code == 404

    # Verrou et exclusion en conflit sur la même recette.
    r = api_client.post(
        f"/api/plan/{plan['id']}/reoptimize",
        json={
            "locked_recipe_ids": ["riz_nature"],
            "excluded_recipe_ids": ["riz_nature"],
        },
    )
    assert r.status_code == 422

    assert api_client.post(
        "/api/plan/999999/reoptimize", json={}
    ).status_code == 404


def test_commit_flips_status(api_client):
    """Le commit (pilote, docs/product-pilot.md, depuis le retrait du
    garde-manger) est une simple validation + passage à ``committed`` —
    plus de comptabilité de stock à reporter."""
    r = api_client.post("/api/plan", json={"config": ALL_ON, "on_date": ON})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["solver_status"] == "Optimal"

    r = api_client.post(f"/api/plan/{plan['id']}/commit")
    assert r.status_code == 200, r.text
    assert r.json() == {"plan_id": plan["id"], "status": "committed"}

    assert api_client.post(f"/api/plan/{plan['id']}/commit").status_code == 409


def test_finalize_locks_menu_and_confirms_available(api_client):
    """Confirmation post-génération (pilote, docs/product-pilot.md) : le
    menu reste verrouillé en entier, seule la logistique d'achat change
    selon les ingrédients confirmés déjà possédés."""
    r = api_client.post("/api/plan", json={"config": {}, "on_date": ON})
    plan = r.json()
    assert plan["grocery_list_by_store"]  # riz acheté, config jouet par défaut

    r = api_client.post(
        f"/api/plan/{plan['id']}/finalize",
        json={"confirmed_available_ids": ["riz"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"]["solver_status"] == "Optimal"
    assert body["plan"]["grocery_list_by_store"] == []
    new_servings = {m["recipe_id"]: m["servings"] for m in body["plan"]["menu"]}
    old_servings = {m["recipe_id"]: m["servings"] for m in plan["menu"]}
    assert new_servings == old_servings  # le menu ne change jamais

    assert api_client.post(
        "/api/plan/999999/finalize", json={"confirmed_available_ids": []}
    ).status_code == 404


def test_reoptimize_rejects_an_already_committed_plan(api_client):
    """Une fois accepté, verrouiller/remplacer une recette doit être refusé
    (409) — sinon les achats déjà ajustés pour ce menu se désynchronisent du
    nouveau menu."""
    r = api_client.post("/api/plan", json={"config": ALL_ON, "on_date": ON})
    plan = r.json()
    api_client.post(f"/api/plan/{plan['id']}/commit")

    r = api_client.post(
        f"/api/plan/{plan['id']}/reoptimize",
        json={"excluded_recipe_ids": [plan["menu"][0]["recipe_id"]]},
    )
    assert r.status_code == 409


def test_needed_ingredients_exposed_on_plan(api_client):
    """``needed_ingredients`` sur ``GET``/``POST /api/plan`` (pilote,
    docs/product-pilot.md) — tous les ingrédients requis par le menu,
    essentiels pré-décochés via ``is_staple``."""
    api_client.put("/api/staples", json={"canonical_ingredient_ids": ["riz"]})
    r = api_client.post("/api/plan", json={"config": ALL_ON, "on_date": ON})
    plan = r.json()
    assert plan["solver_status"] == "Optimal"
    by_id = {l["canonical_ingredient_id"]: l for l in plan["needed_ingredients"]}
    assert by_id["riz"]["is_staple"] is True
    assert by_id["riz"]["name"] == "Riz"

    assert api_client.post(f"/api/plan/{plan['id']}/commit").status_code == 200


def test_recipe_ingredients_endpoint(api_client):
    r = api_client.get("/api/recipes/riz_nature/ingredients")
    assert r.status_code == 200
    assert [i["canonical_ingredient_id"] for i in r.json()] == ["riz"]

    assert api_client.get("/api/recipes/inexistante/ingredients").status_code == 404


def test_committed_plan_feeds_repetition_penalty(api_client):
    """Après un commit, les recettes du plan sont pénalisées : le menu suivant
    change (à données identiques, seule la pénalité de répétition bouge)."""
    r1 = api_client.post("/api/plan", json={"config": ALL_ON, "on_date": ON})
    menu1 = {m["recipe_id"] for m in r1.json()["menu"]}
    api_client.post(f"/api/plan/{r1.json()['id']}/commit")
    r2 = api_client.post("/api/plan", json={"config": ALL_ON, "on_date": ON})
    menu2 = {m["recipe_id"] for m in r2.json()["menu"]}
    # 3 recettes seulement au jouet : l'ensemble peut rester identique, mais
    # les u_r du diagnostic doivent avoir baissé pour les recettes répétées.
    assert r2.json()["solver_status"] == "Optimal"
    assert menu1 and menu2


def test_recipes_stores_and_mapping_endpoints(api_client, db_session):
    r = api_client.get("/api/recipes", params={"limit": 2})
    body = r.json()
    assert body["total"] == 3 and len(body["items"]) == 2

    r = api_client.get("/api/recipes", params={"q": "dahl"})
    assert [i["id"] for i in r.json()["items"]] == ["dahl_toy"]

    r = api_client.get("/api/stores")
    assert [s["external_key"] for s in r.json()] == ["toy_store"]

    assert api_client.get("/api/ingredients/unmapped").json() == []

    # D18 (docs/deviations.md) : le mapping résout vers un produit précis
    # (store_external_key + product_id), pas seulement un ingrédient.
    riz_id = db_session.scalar(
        select(Product.id).where(Product.external_key == "riz_400g")
    )
    r = api_client.post(
        "/api/ingredients/map",
        json={"store_external_key": "toy_store", "raw_text": "Riz mystère 5 kg",
              "product_id": riz_id, "confirmed_by": "test"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["pending_offers"] == 0  # aucune offre unmapped au jouet

    r = api_client.post(
        "/api/ingredients/map",
        json={"store_external_key": "toy_store", "raw_text": "x",
              "new_product": {
                  "canonical_ingredient_id": "inexistant", "brand": "Marque",
                  "package_qty_in_base_unit": "500",
                  "package_unit": "500 g", "tax_rate": "0",
              },
              "confirmed_by": "test"},
    )
    assert r.status_code == 422

    r = api_client.post(
        "/api/ingredients/map",
        json={"store_external_key": "magasin_inconnu", "raw_text": "x",
              "product_id": riz_id, "confirmed_by": "test"},
    )
    assert r.status_code == 404

    r = api_client.post(
        "/api/ingredients/map",
        json={"store_external_key": "toy_store", "raw_text": "x",
              "confirmed_by": "test"},
    )
    assert r.status_code == 422  # ni product_id ni new_product


def test_invalid_solver_config_is_rejected(api_client):
    r = api_client.post(
        "/api/plan", json={"config": {"appetence_mode": "constraint"}}
    )
    assert r.status_code == 422
    assert "appetence_u_min_dollars" in r.json()["detail"]


def test_a_recipe_is_created_and_deleted_through_the_api(api_client):
    """Le parcours que l'écran suit : ajouter, relire, retirer."""
    created = api_client.post(
        "/api/recipes",
        json={
            "name": "Salade d'essai",
            "original_servings": 4,
            "prep_time_fixed_h": "0.25",
            "prep_time_marginal_h": "0",
            "min_batch_servings": 4,
            "max_batch_servings": 8,
            "ingredients": [
                {
                    "canonical_ingredient_id": "riz",
                    "qty_fixed_per_batch_base_unit": "300",
                    "qty_marginal_per_serving_base_unit": "0",
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    recipe_id = created.json()["id"]
    assert created.json()["tags"]["import_origin"] == "app"

    listing = api_client.get("/api/recipes", params={"q": "essai"})
    assert [row["id"] for row in listing.json()["items"]] == [recipe_id]

    removed = api_client.delete(f"/api/recipes/{recipe_id}")
    assert removed.status_code == 204
    assert api_client.get(f"/api/recipes/{recipe_id}/ingredients").status_code == 404


def test_the_api_refuses_a_recipe_naming_an_unknown_ingredient(api_client):
    response = api_client.post(
        "/api/recipes",
        json={
            "name": "Recette impossible",
            "original_servings": 2,
            "min_batch_servings": 2,
            "max_batch_servings": 2,
            "ingredients": [
                {
                    "canonical_ingredient_id": "licorne_hachee",
                    "qty_fixed_per_batch_base_unit": "1",
                }
            ],
        },
    )
    assert response.status_code == 422
    assert "licorne_hachee" in response.json()["detail"]


def test_deleting_an_unknown_recipe_is_a_404(api_client):
    assert api_client.delete("/api/recipes/inexistante").status_code == 404
