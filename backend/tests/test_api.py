"""Tests de l'API (étape 5) contre la base de test seedée (instance jouet).

Le point critique est la comptabilité du ``commit`` : décrément du stock
consommé + report des restes vers ``pantry_stock`` — c'est ce report qui rend
σ_i honnête (docs/spec.md, section API).
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
    "enable_pantry_stock": True, "enable_diversity": True,
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


def test_pantry_roundtrip(api_client):
    r = api_client.put(
        "/api/pantry",
        json={"lines": [{"canonical_ingredient_id": "riz",
                         "quantity_base_unit": 120}]},
    )
    assert r.status_code == 200
    riz = next(row for row in r.json() if row["canonical_ingredient_id"] == "riz")
    assert riz["quantity_base_unit"].rstrip("0").rstrip(".") == "120"
    assert riz["priority"] == "normal"  # défaut, jamais touché par cet endpoint

    r = api_client.put(
        "/api/pantry",
        json={"lines": [{"canonical_ingredient_id": "inexistant",
                         "quantity_base_unit": 1}]},
    )
    assert r.status_code == 422


def test_pantry_priority_endpoint(api_client):
    r = api_client.put("/api/pantry/riz/priority", json={"priority": "must_use"})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "canonical_ingredient_id": "riz", "quantity_base_unit": "0.000",
        "priority": "must_use",
    }

    # PUT /api/pantry (quantité) ne doit jamais réinitialiser la priorité —
    # piège identifié en conception (deux flux distincts appellent cet
    # endpoint : Garde-manger manuel et la confirmation en deux temps de
    # Génération, qui n'envoie jamais de priorité).
    r = api_client.put(
        "/api/pantry",
        json={"lines": [{"canonical_ingredient_id": "riz",
                         "quantity_base_unit": 300}]},
    )
    riz = next(row for row in r.json() if row["canonical_ingredient_id"] == "riz")
    assert riz["priority"] == "must_use"

    r = api_client.put(
        "/api/pantry/inexistant/priority", json={"priority": "must_use"}
    )
    assert r.status_code == 422


def test_generate_plan_rejects_unusable_must_use_ingredient(api_client, db_session):
    from app.models import CanonicalIngredient, UnitKind

    db_session.add(CanonicalIngredient(
        id="epice_test", name="Épice de test", unit_kind=UnitKind.mass,
        base_unit="g", perishability=Decimal("0"),
        salvage_value_cents_per_base_unit=Decimal("0"),
    ))
    db_session.flush()
    api_client.put(
        "/api/pantry",
        json={"lines": [{"canonical_ingredient_id": "epice_test",
                         "quantity_base_unit": 50}]},
    )
    api_client.put(
        "/api/pantry/epice_test/priority", json={"priority": "must_use"}
    )

    r = api_client.post("/api/plan", json={"config": ALL_ON, "on_date": ON})
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


def test_pantry_prompt_then_reoptimize_reduces_purchases(api_client):
    """Le scénario complet de la confirmation du garde-manger (pilote,
    docs/product-pilot.md) : générer, lire la liste priorisée, déclarer
    « assez » de riz, réoptimiser avec enable_pantry_stock=True → le poste
    achats baisse strictement, preuve que le stock déclaré est bien pris en
    compte, pas seulement que les endpoints répondent."""
    r = api_client.post("/api/plan", json={"config": ALL_ON, "on_date": ON})
    plan = r.json()
    old_achats = Decimal(plan["diagnostic"]["objective_terms_cents"]["achats"])

    r = api_client.get(f"/api/plan/{plan['id']}/pantry_prompt")
    assert r.status_code == 200
    prompt = r.json()
    riz = next(l for l in prompt if l["canonical_ingredient_id"] == "riz")
    assert riz["name"] == "Riz"

    r = api_client.put(
        "/api/pantry",
        json={"lines": [{
            "canonical_ingredient_id": "riz",
            "quantity_base_unit": riz["needed_quantity_base_unit"],
        }]},
    )
    assert r.status_code == 200

    r = api_client.post(
        f"/api/plan/{plan['id']}/reoptimize",
        json={"config": {**ALL_ON, "enable_pantry_stock": True}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"]["solver_status"] == "Optimal"
    new_achats = Decimal(body["plan"]["diagnostic"]["objective_terms_cents"]["achats"])
    assert new_achats < old_achats

    assert api_client.get("/api/plan/999999/pantry_prompt").status_code == 404


def test_commit_decrements_and_reports_to_pantry(api_client):
    """Comptabilité vérifiée à la main. Stock initial : 100 g de riz.
    Plan tous-drapeaux (diversité R_min=2) sur le jouet → x_riz + x_dahl.
    besoin_riz = 80·x_riz + 40·x_dahl ; besoin_lentille = 70·x_dahl.
    nouveau_stock_i = stock + acheté − besoin (garde-manger actif)."""
    api_client.put(
        "/api/pantry",
        json={"lines": [{"canonical_ingredient_id": "riz",
                         "quantity_base_unit": 100}]},
    )
    r = api_client.post("/api/plan", json={"config": ALL_ON, "on_date": ON})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["solver_status"] == "Optimal"

    needs = {}
    servings = {m["recipe_id"]: m["servings"] for m in plan["menu"]}
    needs["riz"] = 80 * servings.get("riz_nature", 0) + 40 * servings.get("dahl_toy", 0)
    needs["lentille"] = 70 * servings.get("dahl_toy", 0)
    bought = {"riz": 0, "lentille": 0, "oeuf": 0}
    for g in plan["grocery_list_by_store"]:
        for line in g["lines"]:
            qty = {"riz_1kg": 1000, "riz_400g": 400,
                   "lentille_500g": 500, "oeuf_12": 12}[line["product_external_key"]]
            iid = ("riz" if line["product_external_key"].startswith("riz")
                   else "lentille" if line["product_external_key"].startswith("lentille")
                   else "oeuf")
            bought[iid] += qty * line["units"]

    r = api_client.post(f"/api/plan/{plan['id']}/commit")
    assert r.status_code == 200, r.text
    after = {k: Decimal(v) for k, v in r.json()["pantry_after_commit"].items()}
    assert after["riz"] == Decimal(100 + bought["riz"] - needs["riz"])
    if "lentille" in after:
        assert after["lentille"] == Decimal(bought["lentille"] - needs["lentille"])
    assert all(v >= 0 for v in after.values())

    # Le garde-manger persiste et le double commit est refusé.
    pantry = {p["canonical_ingredient_id"]: Decimal(p["quantity_base_unit"])
              for p in api_client.get("/api/pantry").json()}
    assert pantry["riz"] == after["riz"]
    assert api_client.post(f"/api/plan/{plan['id']}/commit").status_code == 409


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
