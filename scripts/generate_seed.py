"""Génère les fichiers JSON versionnés de ``seed/main`` et ``seed/toy``.

Déterministe (random seedé) : relancer produit exactement les mêmes fichiers.
Le contrat du projet, ce sont les JSON produits — ce script n'est qu'un outil
de fabrication, il n'est jamais importé par l'application.

Exigences (docs/spec.md, « Données de seed ») :
- catalogue canonique généraliste séparé du sous-ensemble de démonstration ;
- périssabilité et récupération à NULL, densités seulement si établies ;
- ~40 recettes cohérentes partageant des ingrédients, τ^fixe et β variés ;
- 4 magasins dont deux partageant un shopping_center_id ;
- ~80 produits, plusieurs formats par ingrédient, rabais actifs + historique ;
- instance jouet séparée (3 recettes, 4 produits, 1 magasin).
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

from catalog_seed_data import family_rows
from generate_catalog import main as generate_catalog_files

ROOT = Path(__file__).resolve().parent.parent
rng = random.Random(20260810)

# Lundi de la « semaine courante » de la circulaire (fixe pour déterminisme).
CURRENT_MONDAY = date(2026, 8, 10)

def iso_week(monday: date) -> str:
    y, w, _ = monday.isocalendar()
    return f"{y}-W{w:02d}"


# --------------------------------------------------------------------------
# Sous-ensemble historique de 23 ingrédients utilisé pour fabriquer les
# recettes, produits et prix de démonstration. Le catalogue canonique complet
# provient de ``catalog_seed_data.py`` et de la curation FCÉN.
#
# σ (salvage_value_cents_per_base_unit) n'est plus une valeur indépendante
# ici : ingredients_json() le DÉRIVE de perishability, sigma = (1 -
# perishability) * 0,8 * prix_plancher — nettement sous la borne 0,8·min
# (prix taxé/unité) de l'assertion 1 par construction (ratio ≤ 1). Le riz
# est proche de sa borne parce que sa périssabilité est basse (0,02) ; la
# coriandre et les épinards sont à 1,0 pour donner exactement σ = 0
# (exigé tel quel par docs/spec.md, § Données de seed).
# (id, name, unit_kind, base_unit, perishability, density)
INGREDIENTS = [
    ("riz_basmati", "Riz basmati", "mass", "g", 0.02, None),
    ("farine_tout_usage", "Farine tout usage", "mass", "g", 0.03, None),
    ("lentille_verte", "Lentilles vertes sèches", "mass", "g", 0.02, None),
    ("poulet_cuisse", "Cuisses de poulet", "mass", "g", 0.85, None),
    ("boeuf_hache", "Bœuf haché mi-maigre", "mass", "g", 0.85, None),
    ("tofu_ferme", "Tofu ferme", "mass", "g", 0.60, None),
    ("oignon_jaune", "Oignon jaune", "mass", "g", 0.15, None),
    ("carotte", "Carotte", "mass", "g", 0.25, None),
    ("pomme_de_terre", "Pomme de terre", "mass", "g", 0.15, None),
    ("tomate_conserve", "Tomates en conserve", "mass", "g", 0.05, None),
    ("cheddar", "Cheddar", "mass", "g", 0.40, None),
    ("beurre", "Beurre salé", "mass", "g", 0.20, None),
    ("coriandre_fraiche", "Coriandre fraîche", "mass", "g", 1.0, None),
    ("epinard_frais", "Épinards frais", "mass", "g", 1.0, None),
    ("lait_325", "Lait 3,25 %", "volume", "ml", 0.70, 1.03),
    ("huile_olive", "Huile d'olive", "volume", "ml", 0.02, 0.91),
    ("sauce_soja", "Sauce soja", "volume", "ml", 0.02, 1.10),
    ("creme_35", "Crème 35 %", "volume", "ml", 0.75, 0.98),
    ("bouillon_poulet", "Bouillon de poulet", "volume", "ml", 0.30, 1.00),
    ("oeuf", "Œuf de calibre gros", "count", "unit", 0.30, None),
    ("tortilla", "Tortilla de blé", "count", "unit", 0.35, None),
    ("gousse_ail", "Gousse d'ail", "count", "unit", 0.10, None),
    ("feuille_laurier", "Feuille de laurier séchée", "count", "unit", 0.02, None),
]

# --------------------------------------------------------------------------
# Recettes — (id, name, π, τfix_h, τmarg_h, β, m, tags, diet, allerg, equip,
#             [(ingredient, qty_fixe/lot, qty_marg/portion)])
V, VG = ["vegetarien"], ["vegetalien", "vegetarien"]
R = [
    ("chili_lentilles", "Chili aux lentilles", 4, 0.4, 0.05, 2, 12,
     {"cuisine": "tex-mex", "saison": "hiver"}, VG, [], ["grande_casserole"],
     [("huile_olive", 15, 0), ("oignon_jaune", 80, 20), ("gousse_ail", 2, 0),
      ("lentille_verte", 0, 60), ("tomate_conserve", 0, 100), ("carotte", 0, 30)]),
    ("chili_boeuf", "Chili con carne", 4, 0.5, 0.06, 2, 12,
     {"cuisine": "tex-mex", "saison": "hiver"}, [], [], ["grande_casserole"],
     [("huile_olive", 15, 0), ("oignon_jaune", 80, 20), ("gousse_ail", 2, 0),
      ("boeuf_hache", 0, 110), ("tomate_conserve", 0, 100)]),
    ("dahl_lentilles", "Dahl de lentilles", 4, 0.3, 0.04, 2, 10,
     {"cuisine": "indienne", "saison": "toutes"}, VG, [], [],
     [("huile_olive", 15, 0), ("oignon_jaune", 60, 15), ("gousse_ail", 2, 0),
      ("lentille_verte", 0, 70), ("bouillon_poulet", 0, 150),
      ("coriandre_fraiche", 10, 2)]),
    ("riz_frit_oeuf", "Riz frit aux œufs", 3, 0.2, 0.05, 2, 8,
     {"cuisine": "asiatique", "saison": "toutes"}, V, ["oeuf", "soja"], ["wok"],
     [("riz_basmati", 0, 75), ("oeuf", 0, 1), ("sauce_soja", 10, 10),
      ("carotte", 0, 25), ("huile_olive", 15, 0)]),
    ("saute_tofu_soja", "Sauté de tofu à la sauce soja", 3, 0.25, 0.05, 2, 9,
     {"cuisine": "asiatique", "saison": "toutes"}, VG, ["soja"], ["wok"],
     [("tofu_ferme", 0, 100), ("sauce_soja", 15, 10), ("gousse_ail", 2, 0),
      ("carotte", 0, 35), ("riz_basmati", 0, 70), ("huile_olive", 15, 0)]),
    ("omelette_fromage", "Omelette au fromage", 2, 0.1, 0.08, 1, 6,
     {"cuisine": "francaise", "saison": "toutes"}, V, ["oeuf", "lactose"], [],
     [("oeuf", 0, 2), ("beurre", 10, 0), ("cheddar", 0, 25), ("lait_325", 0, 15)]),
    ("quiche_epinards", "Quiche aux épinards", 6, 0.7, 0.03, 4, 12,
     {"cuisine": "francaise", "saison": "toutes"}, V, ["oeuf", "lactose", "gluten"],
     ["four"],
     [("farine_tout_usage", 200, 0), ("beurre", 100, 0), ("oeuf", 1, 0.5),
      ("creme_35", 0, 40), ("epinard_frais", 0, 40), ("cheddar", 0, 20)]),
    ("pate_chinois", "Pâté chinois revisité", 6, 0.6, 0.04, 3, 12,
     {"cuisine": "quebecoise", "saison": "hiver"}, [], ["lactose"], ["four"],
     [("boeuf_hache", 0, 90), ("pomme_de_terre", 0, 180), ("carotte", 0, 40),
      ("beurre", 30, 0), ("lait_325", 0, 25), ("oignon_jaune", 60, 0)]),
    ("poulet_braise_laurier", "Poulet braisé au laurier", 4, 0.5, 0.05, 3, 10,
     {"cuisine": "francaise", "saison": "hiver"}, [], [], ["cocotte"],
     [("poulet_cuisse", 0, 160), ("feuille_laurier", 2, 0), ("oignon_jaune", 80, 0),
      ("bouillon_poulet", 200, 50), ("carotte", 0, 40), ("gousse_ail", 3, 0)]),
    ("curry_poulet_coco", "Curry de poulet crémeux", 4, 0.45, 0.05, 2, 10,
     {"cuisine": "indienne", "saison": "toutes"}, [], ["lactose"], [],
     [("poulet_cuisse", 0, 140), ("creme_35", 0, 45), ("oignon_jaune", 70, 10),
      ("gousse_ail", 2, 0), ("riz_basmati", 0, 70), ("coriandre_fraiche", 8, 2)]),
    ("tacos_boeuf", "Tacos au bœuf", 3, 0.3, 0.07, 2, 9,
     {"cuisine": "tex-mex", "saison": "ete"}, [], ["gluten", "lactose"], [],
     [("tortilla", 0, 2), ("boeuf_hache", 0, 100), ("oignon_jaune", 40, 10),
      ("cheddar", 0, 20), ("coriandre_fraiche", 8, 2)]),
    ("tacos_tofu", "Tacos au tofu épicé", 3, 0.3, 0.07, 2, 9,
     {"cuisine": "tex-mex", "saison": "ete"}, VG, ["gluten", "soja"], [],
     [("tortilla", 0, 2), ("tofu_ferme", 0, 90), ("oignon_jaune", 40, 10),
      ("sauce_soja", 10, 5), ("coriandre_fraiche", 8, 2)]),
    ("potage_carotte", "Potage de carottes", 4, 0.35, 0.03, 3, 12,
     {"cuisine": "francaise", "saison": "hiver"}, V, ["lactose"], ["mixeur"],
     [("carotte", 0, 120), ("oignon_jaune", 60, 0), ("bouillon_poulet", 0, 180),
      ("creme_35", 0, 20), ("beurre", 20, 0)]),
    ("soupe_poulet_riz", "Soupe poulet et riz", 4, 0.4, 0.03, 3, 12,
     {"cuisine": "quebecoise", "saison": "hiver"}, [], [], ["grande_casserole"],
     [("poulet_cuisse", 0, 70), ("riz_basmati", 0, 30), ("carotte", 0, 30),
      ("bouillon_poulet", 0, 220), ("feuille_laurier", 1, 0), ("oignon_jaune", 50, 0)]),
    ("gratin_dauphinois", "Gratin dauphinois", 6, 0.5, 0.03, 4, 12,
     {"cuisine": "francaise", "saison": "hiver"}, V, ["lactose"], ["four"],
     [("pomme_de_terre", 0, 200), ("creme_35", 0, 50), ("lait_325", 0, 40),
      ("gousse_ail", 2, 0), ("cheddar", 0, 15), ("beurre", 15, 0)]),
    ("crepes_salees", "Crêpes salées jambon-fromage sans jambon", 4, 0.3, 0.06, 2, 10,
     {"cuisine": "francaise", "saison": "toutes"}, V, ["gluten", "oeuf", "lactose"], [],
     [("farine_tout_usage", 0, 60), ("oeuf", 1, 0.5), ("lait_325", 0, 80),
      ("beurre", 20, 0), ("cheddar", 0, 20)]),
    ("galettes_lentilles", "Galettes de lentilles", 4, 0.4, 0.05, 2, 10,
     {"cuisine": "fusion", "saison": "toutes"}, V, ["oeuf", "gluten"], [],
     [("lentille_verte", 0, 55), ("oeuf", 1, 0.25), ("farine_tout_usage", 0, 20),
      ("oignon_jaune", 40, 10), ("huile_olive", 20, 0)]),
    ("riz_pilaf_poulet", "Riz pilaf au poulet", 4, 0.35, 0.04, 2, 10,
     {"cuisine": "fusion", "saison": "toutes"}, [], [], [],
     [("riz_basmati", 0, 75), ("poulet_cuisse", 0, 120), ("bouillon_poulet", 0, 120),
      ("oignon_jaune", 60, 0), ("beurre", 20, 0), ("feuille_laurier", 1, 0)]),
    ("tortilla_espagnole", "Tortilla espagnole", 4, 0.4, 0.04, 2, 8,
     {"cuisine": "espagnole", "saison": "toutes"}, V, ["oeuf"], [],
     [("pomme_de_terre", 0, 150), ("oeuf", 0, 1.5), ("oignon_jaune", 70, 0),
      ("huile_olive", 40, 5)]),
    ("saag_tofu", "Saag au tofu", 4, 0.4, 0.05, 2, 10,
     {"cuisine": "indienne", "saison": "toutes"}, V, ["soja", "lactose"], ["mixeur"],
     [("epinard_frais", 0, 90), ("tofu_ferme", 0, 90), ("creme_35", 0, 25),
      ("oignon_jaune", 60, 0), ("gousse_ail", 3, 0), ("riz_basmati", 0, 60)]),
]

# Variantes générées pour atteindre ~40 recettes cohérentes : chaque base
# ci-dessus reçoit une déclinaison « familiale » (lot min plus grand, temps
# fixe amorti) ou « express » (lot min petit, temps marginal plus haut).
VARIANTS = []
for (rid, name, pi, tf, tm, b, m, tags, diet, alg, eq, ings) in R:
    VARIANTS.append((
        f"{rid}_familial", f"{name} — format familial", pi * 2,
        round(tf * 1.3, 3), round(tm * 0.8, 3), max(b * 2, 4), m + 4,
        {**tags, "format": "familial"}, diet, alg, eq,
        [(i, round(qf * 1.5, 3), qm) for (i, qf, qm) in ings],
    ))
ALL_RECIPES = R + VARIANTS  # 20 + 20 = 40

# --------------------------------------------------------------------------
STORES = [
    {"external_key": "maxiprix_lebourgneuf", "banner": "Maxi-Prix",
     "address": "1000 boul. des Épinettes", "lat": 45.5602, "lng": -73.6512,
     "shopping_center_id": "centre_les_rives"},
    {"external_key": "superfrais_lebourgneuf", "banner": "SuperFrais",
     "address": "1010 boul. des Épinettes", "lat": 45.5598, "lng": -73.6505,
     "shopping_center_id": "centre_les_rives"},
    {"external_key": "marche_central", "banner": "Marché Central",
     "address": "250 rue du Marché", "lat": 45.5210, "lng": -73.5730,
     "shopping_center_id": None},
    {"external_key": "epicier_du_coin", "banner": "L'Épicier du Coin",
     "address": "12 rue Locale", "lat": 45.5320, "lng": -73.5905,
     "shopping_center_id": None},
]

# Positionnement prix par bannière (stable) : Maxi-Prix casse les prix,
# l'Épicier du Coin (proche du domicile) est un dépanneur cher — le compromis
# distance/prix cesse d'être théorique.
STORE_PRICE_FACTOR = {
    "maxiprix_lebourgneuf": 0.85,
    "superfrais_lebourgneuf": 1.02,
    "marche_central": 1.00,
    "epicier_du_coin": 1.12,
}

BRANDS = ["Maison Rivard", "Val-Mont", "Sans Nom", "Récolte d'Or"]

# Formats par unit_kind : (facteur de taille, libellé)
FORMATS = {
    "mass": [(454, "454 g"), (900, "900 g"), (1800, "1,8 kg"), (2270, "2,27 kg")],
    "volume": [(500, "500 ml"), (1000, "1 L"), (2000, "2 L")],
    "count": [(6, "paquet de 6"), (12, "paquet de 12"), (30, "paquet de 30")],
}
# Prix indicatif régulier en cents par unité de base (avant format).
BASE_PRICE_CENTS_PER_UNIT = {
    "riz_basmati": 0.45, "farine_tout_usage": 0.18, "lentille_verte": 0.35,
    "poulet_cuisse": 0.85, "boeuf_hache": 1.30, "tofu_ferme": 0.75,
    "oignon_jaune": 0.22, "carotte": 0.18, "pomme_de_terre": 0.14,
    "tomate_conserve": 0.28, "cheddar": 1.80, "beurre": 1.60,
    "coriandre_fraiche": 1.20, "epinard_frais": 1.10, "lait_325": 0.22,
    "huile_olive": 1.30, "sauce_soja": 0.60, "creme_35": 0.85,
    "bouillon_poulet": 0.20, "oeuf": 55.0, "tortilla": 62.0, "gousse_ail": 12.0, "feuille_laurier": 9.0,
}
# La plupart des aliments de base sont détaxés ; quelques produits transformés
# portent le taux combiné TPS+TVQ.
TAXED = {"tortilla": 0.14975}


def build_products() -> list[dict]:
    products = []
    for (iid, _n, kind, _bu, _p, _d) in INGREDIENTS:
        n_formats = 4 if kind == "mass" else 3
        fmts = FORMATS[kind][:n_formats]
        # hash(iid) est randomisé par processus (PYTHONHASHSEED) depuis
        # Python 3.3 — jamais reproductible d'un lancement à l'autre malgré
        # ce que prétendait le docstring du module. random.Random(clé) est
        # le seul générateur réellement déterministe ici, même motif que
        # key_rng plus bas pour l'assortiment magasin/produit.
        brand_offset = random.Random(f"brand|{iid}").randrange(len(BRANDS))
        for k, (size, label) in enumerate(fmts):
            brand = BRANDS[(brand_offset + k) % len(BRANDS)]
            products.append({
                "external_key": f"{iid}_f{size}",
                "canonical_ingredient_id": iid,
                "brand": brand,
                "package_qty_in_base_unit": size,
                "package_unit": label,
                "tax_rate": TAXED.get(iid, 0.0),
            })
    return products


def build_raw_offers(products: list[dict]) -> list[dict]:
    """4 semaines de prix (3 d'historique + courante), rabais sur ~25 % des
    couples (produit, magasin) de la semaine courante, dégressif par volume."""
    offers = []
    weeks = [CURRENT_MONDAY - timedelta(weeks=w) for w in (3, 2, 1, 0)]

    # Assortiment et facteur de prix DÉTERMINISTES par (magasin, produit) :
    # le prix régulier est stable d'une semaine à l'autre — c'est ce qui rend
    # l'historique capable de distinguer un vrai rabais d'un prix régulier
    # annoncé en gros caractères (docs/spec.md, table `price`).
    assortment: dict[tuple[str, str], int] = {}
    for store in STORES:
        for prod in products:
            key_rng = random.Random(f"{store['external_key']}|{prod['external_key']}")
            if key_rng.random() < 0.15:
                continue  # ce magasin ne tient pas ce format
            iid = prod["canonical_ingredient_id"]
            per_unit = BASE_PRICE_CENTS_PER_UNIT[iid]
            size = prod["package_qty_in_base_unit"]
            base = STORE_PRICE_FACTOR[store["external_key"]]
            store_factor = base * (0.95 + 0.10 * key_rng.random())  # jitter par couple
            volume_factor = max(0.78, 1.0 - 0.05 * (size > 500) - 0.07 * (size > 1500))
            regular = max(int(round(per_unit * size * store_factor * volume_factor)), 99)
            assortment[(store["external_key"], prod["external_key"])] = regular

    for monday in weeks:
        wk = iso_week(monday)
        for store in STORES:
            for prod in products:
                key = (store["external_key"], prod["external_key"])
                if key not in assortment:
                    continue
                regular = assortment[key]
                # Rabais chaque semaine (~25 %) : l'historique contient aussi
                # de vraies promos passées, pas seulement des prix plats.
                promo = rng.random() < 0.25
                price = int(round(regular * (0.65 + 0.15 * rng.random()))) if promo else regular
                offers.append({
                    "store_external_key": store["external_key"],
                    "week": wk,
                    "raw_text": f"{prod['brand']} — {prod['external_key']} {prod['package_unit']}",
                    "product_external_key": prod["external_key"],
                    "price_cents_cad": price,
                    "regular_price_cents_cad": regular,
                    "is_promo": promo,
                    "valid_from": monday.isoformat(),
                    "valid_to": (monday + timedelta(days=6)).isoformat(),
                })
    return offers


def recipes_json() -> list[dict]:
    out = []
    for (rid, name, pi, tf, tm, b, m, tags, diet, alg, eq, ings) in ALL_RECIPES:
        out.append({
            "id": rid, "name": name, "original_servings": pi,
            "prep_time_fixed_h": str(tf), "prep_time_marginal_h": str(tm),
            "min_batch_servings": b, "max_batch_servings": m,
            "tags": tags, "required_equipment": eq,
            "diet_flags": diet, "allergen_flags": alg,
            "ingredients": [
                {"canonical_ingredient_id": i,
                 "qty_fixed_per_batch_base_unit": str(qf),
                 "qty_marginal_per_serving_base_unit": str(qm),
                 "substitutable": False}
                for (i, qf, qm) in ings
            ],
        })
    return out


def ingredients_json(products: list[dict], offers: list[dict]) -> list[dict]:
    """sigma est DÉRIVÉ de la périssabilité, contre les prix générés (semaine
    courante) : sigma_i = (1 - perishability_i) * 0,8 * prix_plancher_i —
    un ingrédient stable (perishability≈0) garde presque tout le plafond
    permis par l'assertion 1 ; un ingrédient périssable (perishability≈1)
    tombe à ≈0, jamais crédité comme s'il allait survivre à la semaine.
    ratio = 1 - perishability ∈ [0, 1] (perishability est déjà borné 0-1 en
    base) : l'assertion 1 tient par construction, et reste vraie si les prix
    changent, exactement comme l'ancien ratio pseudo-aléatoire — sauf que
    celui-ci est dérivé d'une vraie donnée par ingrédient plutôt qu'arbitraire
    (vérifié empiriquement contre le solveur avant d'être appliqué ici, voir
    CLAUDE.md)."""
    pk = {p["external_key"]: p for p in products}
    wk = iso_week(CURRENT_MONDAY)
    min_per_unit: dict[str, float] = {}
    for o in offers:
        if o["week"] != wk:
            continue
        prod = pk[o["product_external_key"]]
        per = o["price_cents_cad"] * (1 + prod["tax_rate"]) / prod["package_qty_in_base_unit"]
        iid = prod["canonical_ingredient_id"]
        min_per_unit[iid] = min(min_per_unit.get(iid, float("inf")), per)
    out = []
    for (iid, n, k, bu, p, d) in INGREDIENTS:
        sigma = round((1 - p) * 0.8 * min_per_unit[iid], 6)
        out.append({"id": iid, "name": n, "unit_kind": k, "base_unit": bu,
                    "perishability": p, "salvage_value_cents_per_base_unit": sigma,
                    "density_g_per_ml": d})
    return out


HOUSEHOLD = {
    "profile": {
        "id": "default",
        "home_lat": 45.5285, "home_lng": -73.5980,
        "time_value_cents_per_hour": 1500,     # κ = 15,00 $/h
        "meals_per_horizon": 14,               # n_repas
        "demand_slack_epsilon": 0.10,          # ε (D9) : ⌈D⌉ ≤ Σx ≤ ⌈D(1+ε)⌉
        "max_store_visits": 2,                 # K
        "min_distinct_recipes": 4,             # R_min (valeur de départ, spec)
        "max_share_per_recipe": 0.3,           # α (valeur de départ, spec)
        "diet_flags": [],
        "allergen_flags": [],
        "taste_preferences": {"liked_tags": ["tex-mex", "asiatique"],
                              "disliked_tags": ["espagnole", "quebecoise"]},
        "available_equipment": ["four", "grande_casserole", "wok", "mixeur", "cocotte"],
        "max_prep_time_per_meal_h": 1.5,
    },
    "members": [
        {"name": "Alex", "appetite_coefficient": 1.0},
        {"name": "Camille", "appetite_coefficient": 1.0},
        {"name": "Noa", "appetite_coefficient": 0.6},
    ],
    #: Essentiels (staples, pilote, docs/product-pilot.md) — simple
    #: appartenance, sans quantité ; remplace l'ancien garde-manger
    #: (pantry_stock, retiré).
    "staples": ["riz_basmati", "huile_olive", "feuille_laurier"],
}


# --------------------------------------------------------------------------
# Instance jouet : 3 recettes, 4 produits, 1 magasin, optimum calculable à la
# main (documenté dans seed/toy/README.md, test à l'étape 4).
def toy() -> dict[str, object]:
    ingredients = [
        {"id": "riz", "family_id": "riz", "name": "Riz",
         "unit_kind": "mass", "base_unit": "g",
         "perishability": 0.02, "salvage_value_cents_per_base_unit": 0.1,
         "density_g_per_ml": None},
        {"id": "lentille", "name": "Lentilles", "unit_kind": "mass", "base_unit": "g",
         "perishability": 0.02, "salvage_value_cents_per_base_unit": 0.1,
         "density_g_per_ml": None},
        {"id": "oeuf", "name": "Œuf", "unit_kind": "count", "base_unit": "unit",
         "perishability": 0.3, "salvage_value_cents_per_base_unit": 10.0,
         "density_g_per_ml": None},
    ]
    recipes = [
        {"id": "riz_nature", "name": "Riz nature", "original_servings": 2,
         "prep_time_fixed_h": "0.1", "prep_time_marginal_h": "0.02",
         "min_batch_servings": 1, "max_batch_servings": 8,
         "tags": {}, "required_equipment": [], "diet_flags": [], "allergen_flags": [],
         "ingredients": [{"canonical_ingredient_id": "riz",
                          "qty_fixed_per_batch_base_unit": "0",
                          "qty_marginal_per_serving_base_unit": "80",
                          "substitutable": False}]},
        {"id": "dahl_toy", "name": "Dahl", "original_servings": 2,
         "prep_time_fixed_h": "0.2", "prep_time_marginal_h": "0.03",
         "min_batch_servings": 2, "max_batch_servings": 8,
         "tags": {}, "required_equipment": [], "diet_flags": [], "allergen_flags": [],
         "ingredients": [
             {"canonical_ingredient_id": "lentille",
              "qty_fixed_per_batch_base_unit": "0",
              "qty_marginal_per_serving_base_unit": "70", "substitutable": False},
             {"canonical_ingredient_id": "riz",
              "qty_fixed_per_batch_base_unit": "0",
              "qty_marginal_per_serving_base_unit": "40", "substitutable": False}]},
        {"id": "omelette_toy", "name": "Omelette", "original_servings": 1,
         "prep_time_fixed_h": "0.05", "prep_time_marginal_h": "0.05",
         "min_batch_servings": 1, "max_batch_servings": 4,
         "tags": {}, "required_equipment": [], "diet_flags": [], "allergen_flags": [],
         "ingredients": [{"canonical_ingredient_id": "oeuf",
                          "qty_fixed_per_batch_base_unit": "0",
                          "qty_marginal_per_serving_base_unit": "2",
                          "substitutable": False}]},
    ]
    stores = [{"external_key": "toy_store", "banner": "Toy Store", "address": "1 rue Test",
               "lat": 45.53, "lng": -73.60, "shopping_center_id": None}]
    products = [
        {"external_key": "riz_1kg", "canonical_ingredient_id": "riz", "brand": "Toy",
         "package_qty_in_base_unit": 1000, "package_unit": "1 kg", "tax_rate": 0.0},
        {"external_key": "riz_400g", "canonical_ingredient_id": "riz", "brand": "Toy",
         "package_qty_in_base_unit": 400, "package_unit": "400 g", "tax_rate": 0.0},
        {"external_key": "lentille_500g", "canonical_ingredient_id": "lentille", "brand": "Toy",
         "package_qty_in_base_unit": 500, "package_unit": "500 g", "tax_rate": 0.0},
        {"external_key": "oeuf_12", "canonical_ingredient_id": "oeuf", "brand": "Toy",
         "package_qty_in_base_unit": 12, "package_unit": "douzaine", "tax_rate": 0.0},
    ]
    monday = CURRENT_MONDAY
    wk = iso_week(monday)
    prices = [("riz_1kg", 300), ("riz_400g", 180), ("lentille_500g", 250),
              ("oeuf_12", 450)]
    offers = [{
        "store_external_key": "toy_store", "week": wk,
        "raw_text": f"Toy — {pid}", "product_external_key": pid,
        "price_cents_cad": c, "regular_price_cents_cad": c, "is_promo": False,
        "valid_from": monday.isoformat(),
        "valid_to": (monday + timedelta(days=6)).isoformat(),
    } for (pid, c) in prices]
    household = {
        "profile": {**HOUSEHOLD["profile"], "id": "default",
                    "meals_per_horizon": 4, "min_distinct_recipes": 2,
                    "max_share_per_recipe": 0.75, "max_store_visits": 1},
        "members": [{"name": "Solo", "appetite_coefficient": 1.0}],
        "staples": [],
    }
    return {"ingredient_families.json": [
                row for row in family_rows() if row["id"] == "riz"
            ],
            "canonical_ingredient_aliases.json": [],
            "canonical_ingredients.json": ingredients, "recipes.json": recipes,
            "stores.json": stores, "products.json": products,
            "raw_offers.json": offers, "household.json": household}


def dump(path: Path, obj) -> None:
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    main_dir = ROOT / "seed" / "main"
    toy_dir = ROOT / "seed" / "toy"
    main_dir.mkdir(parents=True, exist_ok=True)
    toy_dir.mkdir(parents=True, exist_ok=True)

    products = build_products()
    offers = build_raw_offers(products)
    # Le module catalogue reste l'unique générateur des familles, alias,
    # crosswalks et événements. On enrichit ensuite uniquement les 23
    # ingrédients historiques dont les paramètres solveur sont réellement
    # calibrés; toutes les nouvelles identités FCÉN conservent NULL.
    generate_catalog_files()
    canonical_ingredients = json.loads(
        (main_dir / "canonical_ingredients.json").read_text(encoding="utf-8")
    )
    calibrated = {row["id"]: row for row in ingredients_json(products, offers)}
    for row in canonical_ingredients:
        if row["id"] in calibrated:
            source = calibrated[row["id"]]
            row["perishability"] = source["perishability"]
            row["salvage_value_cents_per_base_unit"] = (
                source["salvage_value_cents_per_base_unit"]
            )
    dump(main_dir / "canonical_ingredients.json", canonical_ingredients)
    dump(main_dir / "recipes.json", recipes_json())
    dump(main_dir / "stores.json", STORES)
    dump(main_dir / "products.json", products)
    dump(main_dir / "raw_offers.json", offers)
    dump(main_dir / "household.json", HOUSEHOLD)

    for name, obj in toy().items():
        dump(toy_dir / name, obj)

    print(f"seed/main : {len(canonical_ingredients)} ingrédients, {len(ALL_RECIPES)} recettes,"
          f" {len(STORES)} magasins, {len(products)} produits")


if __name__ == "__main__":
    main()
