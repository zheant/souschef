"""Socle curé du catalogue canonique Souschef.

Une ligne représente une identité achetable, jamais une marque, un format ou
un simple attribut de préparation. Les valeurs de périssabilité et de
récupération restent volontairement inconnues. Les densités ne sont présentes
que lorsqu'une valeur était déjà établie dans le catalogue du projet.
"""

from __future__ import annotations

import re
import unicodedata


FAMILIES = [
    ("riz", "Riz", "Rice"),
    ("cereales", "Céréales et grains", "Grains and cereals"),
    ("pates", "Pâtes et nouilles", "Pasta and noodles"),
    ("farines", "Farines et amidons", "Flours and starches"),
    ("legumineuses", "Légumineuses", "Legumes"),
    ("legumes", "Légumes", "Vegetables"),
    ("alliums", "Alliacées", "Alliums"),
    ("herbes", "Herbes fraîches", "Fresh herbs"),
    ("fruits", "Fruits", "Fruit"),
    ("volaille", "Volaille", "Poultry"),
    ("boeuf", "Bœuf", "Beef"),
    ("veau", "Veau", "Veal"),
    ("porc", "Porc", "Pork"),
    ("agneau", "Agneau", "Lamb"),
    ("poissons", "Poissons", "Fish"),
    ("fruits_de_mer", "Fruits de mer", "Seafood"),
    ("oeufs", "Œufs", "Eggs"),
    ("produits_laitiers", "Produits laitiers", "Dairy"),
    ("fromages", "Fromages", "Cheese"),
    ("proteines_vegetales", "Protéines végétales", "Plant proteins"),
    ("huiles", "Huiles et matières grasses", "Oils and fats"),
    ("bouillons", "Bouillons", "Stocks and broths"),
    ("tomates", "Tomates transformées", "Processed tomatoes"),
    ("sauces", "Sauces et condiments", "Sauces and condiments"),
    ("epices", "Épices et assaisonnements", "Spices and seasonings"),
    ("sucres", "Sucres et sirops", "Sugars and syrups"),
    ("patisserie", "Pâtisserie et levants", "Baking ingredients"),
    ("noix_graines", "Noix et graines", "Nuts and seeds"),
    ("pains", "Pains et produits plats", "Bread and flatbreads"),
    ("conserves", "Conserves et ingrédients préparés", "Canned ingredients"),
    ("boissons", "Boissons de cuisine", "Cooking beverages"),
]

# id, famille, nom FR, nom EN, unit_kind, densité g/ml, alias FR additionnels
INGREDIENTS = [
    # Riz
    ("riz_basmati", "riz", "Riz basmati", "Basmati rice", "mass", None, ()),
    ("riz_jasmin", "riz", "Riz jasmin", "Jasmine rice", "mass", None, ()),
    ("riz_blanc_long", "riz", "Riz blanc à grain long", "Long-grain white rice", "mass", None, ()),
    ("riz_brun_long", "riz", "Riz brun à grain long", "Long-grain brown rice", "mass", None, ("riz complet",)),
    ("riz_arborio", "riz", "Riz arborio", "Arborio rice", "mass", None, ("riz à risotto",)),
    ("riz_sushi", "riz", "Riz à sushi", "Sushi rice", "mass", None, ()),
    ("riz_sauvage", "riz", "Riz sauvage", "Wild rice", "mass", None, ()),
    ("riz_etuve", "riz", "Riz étuvé", "Parboiled rice", "mass", None, ()),

    # Céréales, pâtes et farines
    ("avoine_flacons", "cereales", "Flocons d’avoine", "Rolled oats", "mass", None, ("gruau",)),
    ("orge_perle", "cereales", "Orge perlé", "Pearl barley", "mass", None, ()),
    ("quinoa_blanc", "cereales", "Quinoa blanc", "White quinoa", "mass", None, ("quinoa",)),
    ("couscous", "cereales", "Couscous", "Couscous", "mass", None, ()),
    ("boulgour", "cereales", "Boulgour", "Bulgur", "mass", None, ()),
    ("sarrasin_grain", "cereales", "Sarrasin en grains", "Buckwheat groats", "mass", None, ()),
    ("millet", "cereales", "Millet", "Millet", "mass", None, ()),
    ("polenta", "cereales", "Polenta", "Polenta", "mass", None, ()),
    ("semoule_ble", "cereales", "Semoule de blé", "Wheat semolina", "mass", None, ()),
    ("spaghetti", "pates", "Spaghetti", "Spaghetti", "mass", None, ()),
    ("penne", "pates", "Penne", "Penne", "mass", None, ()),
    ("macaroni", "pates", "Macaroni", "Macaroni", "mass", None, ()),
    ("lasagne_seche", "pates", "Lasagnes sèches", "Dried lasagna noodles", "mass", None, ()),
    ("orzo", "pates", "Orzo", "Orzo", "mass", None, ()),
    ("nouille_oeuf", "pates", "Nouilles aux œufs", "Egg noodles", "mass", None, ()),
    ("nouille_riz", "pates", "Nouilles de riz", "Rice noodles", "mass", None, ("vermicelles de riz",)),
    ("pate_soba", "pates", "Nouilles soba", "Soba noodles", "mass", None, ()),
    ("pate_udon", "pates", "Nouilles udon", "Udon noodles", "mass", None, ()),
    ("farine_tout_usage", "farines", "Farine tout usage", "All-purpose flour", "mass", None, ("farine blanche",)),
    ("farine_ble_entier", "farines", "Farine de blé entier", "Whole-wheat flour", "mass", None, ()),
    ("farine_pain", "farines", "Farine à pain", "Bread flour", "mass", None, ()),
    ("farine_amande", "farines", "Farine d’amande", "Almond flour", "mass", None, ("poudre d’amande",)),
    ("farine_coco", "farines", "Farine de noix de coco", "Coconut flour", "mass", None, ()),
    ("farine_mais", "farines", "Farine de maïs", "Corn flour", "mass", None, ()),
    ("farine_riz", "farines", "Farine de riz", "Rice flour", "mass", None, ()),
    ("farine_pois_chiche", "farines", "Farine de pois chiches", "Chickpea flour", "mass", None, ()),
    ("fecule_mais", "farines", "Fécule de maïs", "Cornstarch", "mass", None, ()),
    ("fecule_pomme_de_terre", "farines", "Fécule de pomme de terre", "Potato starch", "mass", None, ()),

    # Légumineuses et protéines végétales
    ("lentille_verte", "legumineuses", "Lentilles vertes sèches", "Dried green lentils", "mass", None, ("lentilles vertes",)),
    ("lentille_rouge", "legumineuses", "Lentilles rouges sèches", "Dried red lentils", "mass", None, ("lentilles corail",)),
    ("lentille_brune", "legumineuses", "Lentilles brunes sèches", "Dried brown lentils", "mass", None, ()),
    ("pois_chiche_sec", "legumineuses", "Pois chiches secs", "Dried chickpeas", "mass", None, ()),
    ("pois_chiche_conserve", "legumineuses", "Pois chiches en conserve", "Canned chickpeas", "mass", None, ()),
    ("haricot_noir_sec", "legumineuses", "Haricots noirs secs", "Dried black beans", "mass", None, ()),
    ("haricot_noir_conserve", "legumineuses", "Haricots noirs en conserve", "Canned black beans", "mass", None, ()),
    ("haricot_rouge_conserve", "legumineuses", "Haricots rouges en conserve", "Canned kidney beans", "mass", None, ()),
    ("haricot_blanc_conserve", "legumineuses", "Haricots blancs en conserve", "Canned white beans", "mass", None, ()),
    ("haricot_pinto_conserve", "legumineuses", "Haricots pinto en conserve", "Canned pinto beans", "mass", None, ()),
    ("pois_casse_sec", "legumineuses", "Pois cassés secs", "Dried split peas", "mass", None, ()),
    ("edamame_surgele", "legumineuses", "Edamames surgelés", "Frozen edamame", "mass", None, ()),
    ("tofu_ferme", "proteines_vegetales", "Tofu ferme", "Firm tofu", "mass", None, ()),
    ("tofu_extra_ferme", "proteines_vegetales", "Tofu extra-ferme", "Extra-firm tofu", "mass", None, ()),
    ("tofu_soyeux", "proteines_vegetales", "Tofu soyeux", "Silken tofu", "mass", None, ()),
    ("tempeh", "proteines_vegetales", "Tempeh", "Tempeh", "mass", None, ()),
    ("seitan", "proteines_vegetales", "Seitan", "Seitan", "mass", None, ()),
    ("proteine_vegetale_texturee", "proteines_vegetales", "Protéine végétale texturée", "Textured vegetable protein", "mass", None, ("PVT",)),

    # Légumes, alliacées et herbes
    ("pomme_de_terre", "legumes", "Pomme de terre", "Potato", "mass", None, ("patate",)),
    ("patate_douce", "legumes", "Patate douce", "Sweet potato", "mass", None, ()),
    ("carotte", "legumes", "Carotte", "Carrot", "mass", None, ()),
    ("panais", "legumes", "Panais", "Parsnip", "mass", None, ()),
    ("betterave", "legumes", "Betterave", "Beet", "mass", None, ()),
    ("navet", "legumes", "Navet", "Turnip", "mass", None, ()),
    ("rutabaga", "legumes", "Rutabaga", "Rutabaga", "mass", None, ()),
    ("brocoli", "legumes", "Brocoli", "Broccoli", "mass", None, ()),
    ("chou_fleur", "legumes", "Chou-fleur", "Cauliflower", "mass", None, ()),
    ("chou_vert", "legumes", "Chou vert", "Green cabbage", "mass", None, ()),
    ("chou_rouge", "legumes", "Chou rouge", "Red cabbage", "mass", None, ()),
    ("chou_frise", "legumes", "Chou frisé", "Kale", "mass", None, ()),
    ("chou_bruxelles", "legumes", "Choux de Bruxelles", "Brussels sprouts", "mass", None, ()),
    ("epinard_frais", "legumes", "Épinards frais", "Fresh spinach", "mass", None, ()),
    ("laitue_romaine", "legumes", "Laitue romaine", "Romaine lettuce", "mass", None, ()),
    ("roquette", "legumes", "Roquette", "Arugula", "mass", None, ()),
    ("celeri", "legumes", "Céleri", "Celery", "mass", None, ()),
    ("concombre", "legumes", "Concombre", "Cucumber", "mass", None, ()),
    ("courgette", "legumes", "Courgette", "Zucchini", "mass", None, ()),
    ("aubergine", "legumes", "Aubergine", "Eggplant", "mass", None, ()),
    ("poivron_rouge", "legumes", "Poivron rouge", "Red bell pepper", "mass", None, ()),
    ("poivron_vert", "legumes", "Poivron vert", "Green bell pepper", "mass", None, ()),
    ("poivron_jaune", "legumes", "Poivron jaune", "Yellow bell pepper", "mass", None, ()),
    ("piment_jalapeno", "legumes", "Piment jalapeño", "Jalapeno pepper", "mass", None, ("jalapeño",)),
    ("champignon_blanc", "legumes", "Champignons blancs", "White mushrooms", "mass", None, ("champignons de Paris",)),
    ("champignon_cremini", "legumes", "Champignons cremini", "Cremini mushrooms", "mass", None, ()),
    ("asperge", "legumes", "Asperges", "Asparagus", "mass", None, ()),
    ("haricot_vert", "legumes", "Haricots verts", "Green beans", "mass", None, ()),
    ("mais_grain_surgele", "legumes", "Maïs en grains surgelé", "Frozen corn kernels", "mass", None, ()),
    ("pois_vert_surgele", "legumes", "Pois verts surgelés", "Frozen green peas", "mass", None, ()),
    ("courge_musquee", "legumes", "Courge musquée", "Butternut squash", "mass", None, ("courge butternut",)),
    ("citrouille_puree", "conserves", "Purée de citrouille", "Pumpkin puree", "mass", None, ()),
    ("oignon_jaune", "alliums", "Oignon jaune", "Yellow onion", "mass", None, ()),
    ("oignon_rouge", "alliums", "Oignon rouge", "Red onion", "mass", None, ()),
    ("oignon_vert", "alliums", "Oignon vert", "Green onion", "mass", None, ("échalote verte",)),
    ("echalote_francaise", "alliums", "Échalote française", "Shallot", "mass", None, ("échalote",)),
    ("poireau", "alliums", "Poireau", "Leek", "mass", None, ()),
    ("gousse_ail", "alliums", "Gousse d’ail", "Garlic clove", "count", None, ("ail",)),
    ("coriandre_fraiche", "herbes", "Coriandre fraîche", "Fresh cilantro", "mass", None, ()),
    ("persil_plat", "herbes", "Persil plat", "Flat-leaf parsley", "mass", None, ("persil italien",)),
    ("persil_frise", "herbes", "Persil frisé", "Curly parsley", "mass", None, ()),
    ("basilic_frais", "herbes", "Basilic frais", "Fresh basil", "mass", None, ()),
    ("menthe_fraiche", "herbes", "Menthe fraîche", "Fresh mint", "mass", None, ()),
    ("aneth_frais", "herbes", "Aneth frais", "Fresh dill", "mass", None, ()),
    ("ciboulette_fraiche", "herbes", "Ciboulette fraîche", "Fresh chives", "mass", None, ()),
    ("thym_frais", "herbes", "Thym frais", "Fresh thyme", "mass", None, ()),
    ("romarin_frais", "herbes", "Romarin frais", "Fresh rosemary", "mass", None, ()),

    # Fruits
    ("pomme", "fruits", "Pomme", "Apple", "mass", None, ()),
    ("poire", "fruits", "Poire", "Pear", "mass", None, ()),
    ("banane", "fruits", "Banane", "Banana", "mass", None, ()),
    ("orange", "fruits", "Orange", "Orange", "mass", None, ()),
    ("citron", "fruits", "Citron", "Lemon", "mass", None, ()),
    ("lime", "fruits", "Lime", "Lime", "mass", None, ("citron vert",)),
    ("pamplemousse", "fruits", "Pamplemousse", "Grapefruit", "mass", None, ()),
    ("avocat", "fruits", "Avocat", "Avocado", "mass", None, ()),
    ("tomate", "fruits", "Tomate fraîche", "Fresh tomato", "mass", None, ("tomate",)),
    ("fraise", "fruits", "Fraises", "Strawberries", "mass", None, ()),
    ("framboise", "fruits", "Framboises", "Raspberries", "mass", None, ()),
    ("bleuet", "fruits", "Bleuets", "Blueberries", "mass", None, ("myrtilles",)),
    ("raisin", "fruits", "Raisins frais", "Fresh grapes", "mass", None, ()),
    ("peche", "fruits", "Pêche", "Peach", "mass", None, ()),
    ("prune", "fruits", "Prune", "Plum", "mass", None, ()),
    ("mangue", "fruits", "Mangue", "Mango", "mass", None, ()),
    ("ananas", "fruits", "Ananas", "Pineapple", "mass", None, ()),
    ("kiwi", "fruits", "Kiwi", "Kiwi", "mass", None, ()),
    ("melon_cantaloup", "fruits", "Cantaloup", "Cantaloupe", "mass", None, ()),
    ("melon_eau", "fruits", "Melon d’eau", "Watermelon", "mass", None, ("pastèque",)),
    ("canneberge_sechee", "fruits", "Canneberges séchées", "Dried cranberries", "mass", None, ()),
    ("raisin_sec", "fruits", "Raisins secs", "Raisins", "mass", None, ()),
    ("datte_sechee", "fruits", "Dattes séchées", "Dried dates", "mass", None, ()),

    # Viandes, poissons et œufs
    ("poulet_cuisse", "volaille", "Cuisses de poulet", "Chicken thighs", "mass", None, ()),
    ("poulet_poitrine", "volaille", "Poitrines de poulet", "Chicken breasts", "mass", None, ()),
    ("poulet_entier", "volaille", "Poulet entier", "Whole chicken", "mass", None, ()),
    ("poulet_hache", "volaille", "Poulet haché", "Ground chicken", "mass", None, ()),
    ("dinde_hachee", "volaille", "Dinde hachée", "Ground turkey", "mass", None, ()),
    ("boeuf_hache", "boeuf", "Bœuf haché mi-maigre", "Medium ground beef", "mass", None, ("bœuf haché",)),
    ("boeuf_hache_maigre", "boeuf", "Bœuf haché maigre", "Lean ground beef", "mass", None, ()),
    ("boeuf_ragout", "boeuf", "Cubes de bœuf à ragoût", "Beef stewing cubes", "mass", None, ("bœuf à ragoût",)),
    ("boeuf_roti_palette", "boeuf", "Rôti de palette de bœuf", "Beef blade roast", "mass", None, ()),
    ("boeuf_bifteck_surlonge", "boeuf", "Bifteck de surlonge", "Sirloin steak", "mass", None, ()),
    ("porc_hache", "porc", "Porc haché", "Ground pork", "mass", None, ()),
    ("porc_cotelette", "porc", "Côtelettes de porc", "Pork chops", "mass", None, ()),
    ("porc_filet", "porc", "Filet de porc", "Pork tenderloin", "mass", None, ()),
    ("bacon", "porc", "Bacon", "Bacon", "mass", None, ()),
    ("jambon_cuit", "porc", "Jambon cuit", "Cooked ham", "mass", None, ()),
    ("saucisse_italienne", "porc", "Saucisses italiennes", "Italian sausages", "mass", None, ()),
    ("agneau_hache", "agneau", "Agneau haché", "Ground lamb", "mass", None, ()),
    ("saumon_filet", "poissons", "Filet de saumon", "Salmon fillet", "mass", None, ("saumon",)),
    ("truite_filet", "poissons", "Filet de truite", "Trout fillet", "mass", None, ("truite",)),
    ("morue_filet", "poissons", "Filet de morue", "Cod fillet", "mass", None, ("morue",)),
    ("tilapia_filet", "poissons", "Filet de tilapia", "Tilapia fillet", "mass", None, ("tilapia",)),
    ("thon_conserve_eau", "poissons", "Thon en conserve dans l’eau", "Canned tuna in water", "mass", None, ("thon en conserve",)),
    ("sardine_conserve", "poissons", "Sardines en conserve", "Canned sardines", "mass", None, ()),
    ("crevette_crue", "fruits_de_mer", "Crevettes crues", "Raw shrimp", "mass", None, ("crevettes",)),
    ("moule", "fruits_de_mer", "Moules", "Mussels", "mass", None, ()),
    ("petoncle", "fruits_de_mer", "Pétoncles", "Scallops", "mass", None, ()),
    ("oeuf", "oeufs", "Œuf de calibre gros", "Large egg", "count", None, ("œuf",)),

    # Produits laitiers et fromages
    ("lait_325", "produits_laitiers", "Lait 3,25 %", "3.25% milk", "volume", 1.03, ("lait entier",)),
    ("lait_2", "produits_laitiers", "Lait 2 %", "2% milk", "volume", None, ()),
    ("lait_1", "produits_laitiers", "Lait 1 %", "1% milk", "volume", None, ()),
    ("lait_ecreme", "produits_laitiers", "Lait écrémé", "Skim milk", "volume", None, ()),
    # FCÉN 2026, aliment 5487 « Babeurre, liquide, 2% M.G. » : 250 ml =
    # 258.876 g, soit 1.036 g/ml.
    ("babeurre", "produits_laitiers", "Babeurre", "Buttermilk", "volume", 1.036, ()),
    ("creme_35", "produits_laitiers", "Crème 35 %", "35% cream", "volume", 0.98, ("crème à fouetter",)),
    # FCÉN 2026, aliment 151 « Crème de table (champêtre), 15% M.G. » : 250
    # ml = 253.593 g, soit 1.014 g/ml.
    ("creme_15", "produits_laitiers", "Crème 15 %", "15% cream", "volume", 1.014, ("crème à cuisson",)),
    ("creme_sure", "produits_laitiers", "Crème sure", "Sour cream", "mass", None, ("crème aigre",)),
    ("yogourt_nature", "produits_laitiers", "Yogourt nature", "Plain yogurt", "mass", None, ("yaourt nature",)),
    ("yogourt_grec", "produits_laitiers", "Yogourt grec nature", "Plain Greek yogurt", "mass", None, ()),
    ("beurre", "huiles", "Beurre salé", "Salted butter", "mass", None, ()),
    ("beurre_non_sale", "huiles", "Beurre non salé", "Unsalted butter", "mass", None, ()),
    ("cheddar", "fromages", "Cheddar", "Cheddar cheese", "mass", None, ()),
    ("mozzarella", "fromages", "Mozzarella", "Mozzarella cheese", "mass", None, ()),
    ("parmesan", "fromages", "Parmesan", "Parmesan cheese", "mass", None, ()),
    ("feta", "fromages", "Feta", "Feta cheese", "mass", None, ()),
    ("fromage_creme", "fromages", "Fromage à la crème", "Cream cheese", "mass", None, ()),
    ("ricotta", "fromages", "Ricotta", "Ricotta cheese", "mass", None, ()),
    ("fromage_cottage", "fromages", "Fromage cottage", "Cottage cheese", "mass", None, ()),
    ("gruyere", "fromages", "Gruyère", "Gruyere cheese", "mass", None, ()),
    ("fromage_bleu", "fromages", "Fromage bleu", "Blue cheese", "mass", None, ()),
    ("halloumi", "fromages", "Halloumi", "Halloumi cheese", "mass", None, ()),

    # Huiles, bouillons, tomates, sauces et conserves
    # FCÉN 2026, aliment 422 « Huile végétale, olive » : 250 ml = 228.233 g,
    # soit 0.913 g/ml. Le seed garde le 0,91 écrit à la main avant l'import du
    # FCÉN : 0,4 % d'écart ne vaut pas de déplacer les prix de 58 recettes.
    ("huile_olive", "huiles", "Huile d’olive", "Olive oil", "volume", 0.91, ()),
    # FCÉN 2026, aliment 451 « Huile végétale, canola (colza) » : 250 ml =
    # 230.347 g, soit 0.921 g/ml.
    ("huile_canola", "huiles", "Huile de canola", "Canola oil", "volume", 0.921, ("huile de colza",)),
    # FCÉN 2026, aliment 451 « Huile végétale, canola (colza) » : 250 ml =
    # 230.347 g, soit 0.921 g/ml.
    ("huile_vegetale", "huiles", "Huile végétale", "Vegetable oil", "volume", 0.921, ()),
    ("huile_sesame", "huiles", "Huile de sésame", "Sesame oil", "volume", None, ()),
    ("huile_coco", "huiles", "Huile de noix de coco", "Coconut oil", "mass", None, ()),
    ("margarine", "huiles", "Margarine", "Margarine", "mass", None, ()),
    ("bouillon_poulet", "bouillons", "Bouillon de poulet", "Chicken broth", "volume", 1.00, ()),
    ("bouillon_boeuf", "bouillons", "Bouillon de bœuf", "Beef broth", "volume", None, ()),
    ("bouillon_legumes", "bouillons", "Bouillon de légumes", "Vegetable broth", "volume", None, ()),
    ("tomate_conserve", "tomates", "Tomates en conserve", "Canned tomatoes", "mass", None, ()),
    ("tomate_conserve_des", "tomates", "Tomates en dés en conserve", "Canned diced tomatoes", "mass", None, ()),
    ("tomate_broyee", "tomates", "Tomates broyées", "Crushed tomatoes", "mass", None, ()),
    ("puree_tomate", "tomates", "Purée de tomates", "Tomato puree", "mass", None, ()),
    ("pate_tomate", "tomates", "Pâte de tomates", "Tomato paste", "mass", None, ()),
    # FCÉN 2026, aliment 2465 « Produits à base de tomates, conserve, sauce »
    # : 250 ml = 258.876 g, soit 1.036 g/ml.
    ("sauce_tomate", "tomates", "Sauce tomate", "Tomato sauce", "volume", 1.036, ()),
    ("sauce_soja", "sauces", "Sauce soja", "Soy sauce", "volume", 1.10, ("sauce soya",)),
    # FCÉN 2026, aliment 14 « Vinaigre, distillé (blanc) » : 125 ml = 126.796
    # g, soit 1.014 g/ml.
    ("vinaigre_blanc", "sauces", "Vinaigre blanc", "White vinegar", "volume", 1.014, ()),
    # FCÉN 2026, aliment 13 « Vinaigre, cidre » : 125 ml = 126.789 g, soit
    # 1.014 g/ml.
    ("vinaigre_cidre", "sauces", "Vinaigre de cidre", "Apple cider vinegar", "volume", 1.014, ()),
    # FCÉN 2026, aliment 6196 « Vinaigre, balsamique » : 250 ml = 269.442 g,
    # soit 1.078 g/ml.
    ("vinaigre_balsamique", "sauces", "Vinaigre balsamique", "Balsamic vinegar", "volume", 1.078, ()),
    # FCÉN 2026, aliment 14 « Vinaigre, distillé (blanc) » : 125 ml = 126.796
    # g, soit 1.014 g/ml.
    ("vinaigre_riz", "sauces", "Vinaigre de riz", "Rice vinegar", "volume", 1.014, ()),
    # FCÉN 2026, aliment 1135 « Sauce, moutarde, brune, prête-à-servir » : 250
    # ml = 260 g, soit 1.040 g/ml. Aliment retenu par substitution déclarée —
    # le FCÉN ne publie pas la dijon; voir config/nutrition-rules.json.
    ("moutarde_dijon", "sauces", "Moutarde de Dijon", "Dijon mustard", "volume", 1.040, ()),
    # FCÉN 2026, aliment 531 « Vinaigrette, mayonnaise, régulière » : 250 ml
    # = 232.46 g, soit 0.930 g/ml.
    ("mayonnaise", "sauces", "Mayonnaise", "Mayonnaise", "volume", 0.930, ()),
    # FCÉN 2026, aliment 2494 « Tomates, ketchup (catsup) » : 250 ml =
    # 253.593 g, soit 1.014 g/ml.
    ("ketchup", "sauces", "Ketchup", "Ketchup", "volume", 1.014, ()),
    # FCÉN 2026, aliment 1133 « Sauce, worcestershire, prête-à-servir » : 250
    # ml = 290.575 g, soit 1.162 g/ml.
    ("sauce_worcestershire", "sauces", "Sauce Worcestershire", "Worcestershire sauce", "volume", 1.162, ()),
    # FCÉN 2026, aliment 4731 « Sauce, poisson, prête-à-servir » : 250 ml =
    # 304.05 g, soit 1.216 g/ml.
    ("sauce_poisson", "sauces", "Sauce de poisson", "Fish sauce", "volume", 1.216, ()),
    # FCÉN 2026, aliment 1029 « Sauce, piments forts, prête-à-servir » : 250
    # ml = 239.796 g, soit 0.959 g/ml.
    ("sauce_piquante", "sauces", "Sauce piquante", "Hot sauce", "volume", 0.959, ()),
    ("lait_coco_conserve", "conserves", "Lait de coco en conserve", "Canned coconut milk", "volume", None, ()),
    ("mais_conserve", "conserves", "Maïs en conserve", "Canned corn", "mass", None, ()),
    ("olive_noire", "conserves", "Olives noires", "Black olives", "mass", None, ()),
    ("olive_verte", "conserves", "Olives vertes", "Green olives", "mass", None, ()),
    ("capre", "conserves", "Câpres", "Capers", "mass", None, ()),
    ("cornichon_aneth", "conserves", "Cornichons à l’aneth", "Dill pickles", "mass", None, ()),

    # Épices, sucres, pâtisserie et noix
    ("sel_table", "epices", "Sel de table", "Table salt", "mass", None, ("sel",)),
    ("poivre_noir", "epices", "Poivre noir", "Black pepper", "mass", None, ()),
    ("paprika", "epices", "Paprika", "Paprika", "mass", None, ()),
    ("paprika_fume", "epices", "Paprika fumé", "Smoked paprika", "mass", None, ()),
    ("cumin_moulu", "epices", "Cumin moulu", "Ground cumin", "mass", None, ()),
    ("coriandre_moulue", "epices", "Coriandre moulue", "Ground coriander", "mass", None, ()),
    ("curcuma_moulu", "epices", "Curcuma moulu", "Ground turmeric", "mass", None, ()),
    ("cannelle_moulue", "epices", "Cannelle moulue", "Ground cinnamon", "mass", None, ()),
    ("muscade_moulue", "epices", "Muscade moulue", "Ground nutmeg", "mass", None, ()),
    ("poudre_chili", "epices", "Poudre de chili", "Chili powder", "mass", None, ()),
    ("flocon_piment", "epices", "Flocons de piment", "Red pepper flakes", "mass", None, ()),
    ("cari_poudre", "epices", "Poudre de cari", "Curry powder", "mass", None, ()),
    ("garam_masala", "epices", "Garam masala", "Garam masala", "mass", None, ()),
    ("origan_seche", "epices", "Origan séché", "Dried oregano", "mass", None, ()),
    ("basilic_seche", "epices", "Basilic séché", "Dried basil", "mass", None, ()),
    ("thym_seche", "epices", "Thym séché", "Dried thyme", "mass", None, ()),
    ("romarin_seche", "epices", "Romarin séché", "Dried rosemary", "mass", None, ()),
    ("feuille_laurier", "epices", "Feuille de laurier séchée", "Dried bay leaf", "count", None, ("feuille de laurier",)),
    ("gingembre_moulu", "epices", "Gingembre moulu", "Ground ginger", "mass", None, ()),
    ("gingembre_frais", "epices", "Gingembre frais", "Fresh ginger", "mass", None, ()),
    ("sucre_blanc", "sucres", "Sucre blanc", "White sugar", "mass", None, ("sucre granulé",)),
    ("cassonade", "sucres", "Cassonade", "Brown sugar", "mass", None, ()),
    ("sucre_glace", "sucres", "Sucre à glacer", "Icing sugar", "mass", None, ("sucre glace",)),
    # FCÉN 2026, aliment 4326 « Confiseries, sirop d'érable, en vrac » : 250
    # ml = 332.857 g, soit 1.331 g/ml.
    ("sirop_erable", "sucres", "Sirop d’érable", "Maple syrup", "volume", 1.331, ()),
    # FCÉN 2026, aliment 4294 « Confiseries, miel, filtre ou extrait » : 100
    # ml = 143.243 g, soit 1.432 g/ml.
    ("miel", "sucres", "Miel", "Honey", "volume", 1.432, ()),
    # FCÉN 2026, aliment 4299 « Confiseries, mélasse de fantaisie » : 250 ml
    # = 356.086 g, soit 1.424 g/ml.
    ("melasse", "sucres", "Mélasse", "Molasses", "volume", 1.424, ()),
    ("levure_chimique", "patisserie", "Poudre à pâte", "Baking powder", "mass", None, ("levure chimique",)),
    ("bicarbonate_soude", "patisserie", "Bicarbonate de soude", "Baking soda", "mass", None, ()),
    ("levure_seche_active", "patisserie", "Levure sèche active", "Active dry yeast", "mass", None, ()),
    ("extrait_vanille", "patisserie", "Extrait de vanille", "Vanilla extract", "volume", None, ()),
    ("cacao_poudre", "patisserie", "Cacao en poudre", "Cocoa powder", "mass", None, ()),
    ("chocolat_noir", "patisserie", "Chocolat noir", "Dark chocolate", "mass", None, ()),
    ("brisure_chocolat", "patisserie", "Brisures de chocolat", "Chocolate chips", "mass", None, ("pépites de chocolat",)),
    ("gelatine_poudre", "patisserie", "Gélatine en poudre", "Powdered gelatin", "mass", None, ()),
    ("noix_amande", "noix_graines", "Amandes", "Almonds", "mass", None, ()),
    ("noix_grenoble", "noix_graines", "Noix de Grenoble", "Walnuts", "mass", None, ("noix",)),
    ("noix_pacane", "noix_graines", "Pacanes", "Pecans", "mass", None, ("noix de pécan",)),
    ("noix_cajou", "noix_graines", "Noix de cajou", "Cashews", "mass", None, ()),
    ("arachide", "noix_graines", "Arachides", "Peanuts", "mass", None, ("cacahuètes",)),
    ("beurre_arachide", "noix_graines", "Beurre d’arachide", "Peanut butter", "mass", None, ()),
    ("graine_sesame", "noix_graines", "Graines de sésame", "Sesame seeds", "mass", None, ()),
    ("graine_tournesol", "noix_graines", "Graines de tournesol", "Sunflower seeds", "mass", None, ()),
    ("graine_citrouille", "noix_graines", "Graines de citrouille", "Pumpkin seeds", "mass", None, ("pepitas",)),
    ("graine_chia", "noix_graines", "Graines de chia", "Chia seeds", "mass", None, ()),
    ("graine_lin", "noix_graines", "Graines de lin", "Flax seeds", "mass", None, ()),
    ("tahini", "noix_graines", "Tahini", "Tahini", "mass", None, ("beurre de sésame",)),

    # Pains et boissons utilisées en cuisine
    ("pain_tranche_blanc", "pains", "Pain blanc tranché", "Sliced white bread", "count", None, ()),
    ("pain_tranche_ble_entier", "pains", "Pain de blé entier tranché", "Sliced whole-wheat bread", "count", None, ()),
    ("pain_pita", "pains", "Pain pita", "Pita bread", "count", None, ()),
    ("tortilla", "pains", "Tortilla de blé", "Flour tortilla", "count", None, ()),
    ("tortilla_mais", "pains", "Tortilla de maïs", "Corn tortilla", "count", None, ()),
    ("chapelure", "pains", "Chapelure", "Breadcrumbs", "mass", None, ()),
    # FCÉN 2026, aliment 2852 « Boisson alcoolisée, vin de table, blanc
    # (11,5% alcool par volume) » : 150 ml = 149.138 g, soit 0.994 g/ml.
    ("vin_blanc_sec", "boissons", "Vin blanc sec", "Dry white wine", "volume", 0.994, ()),
    # FCÉN 2026, aliment 2850 « Boisson alcoolisée, vin de table, rouge
    # (11,5% alcool par volume) » : 150 ml = 149.138 g, soit 0.994 g/ml.
    ("vin_rouge_sec", "boissons", "Vin rouge sec", "Dry red wine", "volume", 0.994, ()),
    # FCÉN 2026, aliment 2943 « Boisson alcoolisée, bière, ordinaire (5%
    # alcool par volume) » : 1 cannette / boite de conserve (355 ml) =
    # 356.561 g, soit 1.004 g/ml.
    ("biere_blonde", "boissons", "Bière blonde", "Lager beer", "volume", 1.004, ()),
    ("jus_orange", "boissons", "Jus d’orange", "Orange juice", "volume", None, ()),
    ("jus_citron", "boissons", "Jus de citron", "Lemon juice", "volume", None, ()),

    # Identités achetables explicitement justifiées par le corpus Cook.
    # Les préparations, marques, alternatives et libellés ambigus n'entrent
    # pas ici; ils restent dans le rapport de revue des recettes.
    ("levure_alimentaire", "proteines_vegetales", "Levure alimentaire", "Nutritional yeast", "mass", None, ()),
    ("poudre_ail", "epices", "Poudre d’ail", "Garlic powder", "mass", None, ()),
    ("poudre_oignon", "epices", "Poudre d’oignon", "Onion powder", "mass", None, ()),
    # FCÉN 2026, aliment 5241 « Boisson à base de plantes, soya, nature, non-
    # enrichie, réfrigérée » : 250 ml = 260.4 g, soit 1.042 g/ml.
    ("lait_soya", "boissons", "Boisson de soya", "Soy milk", "volume", 1.042, ("lait de soya",)),
    ("eau", "boissons", "Eau", "Water", "volume", 1.00, ()),
    ("fumee_liquide", "sauces", "Fumée liquide", "Liquid smoke", "volume", None, ()),
    # FCÉN 2026, aliment 7593 « Sauce, chili, forte, sriracha, prête-à-servir
    # » : 100 ml = 132.653 g, soit 1.327 g/ml.
    ("sriracha", "sauces", "Sauce sriracha", "Sriracha", "volume", 1.327, ()),
    ("harissa", "sauces", "Harissa", "Harissa sauce", "volume", None, ()),
    ("fromage_grains", "fromages", "Fromage en grains", "Cheese curds", "mass", None, ()),
    ("pesto_basilic", "sauces", "Pesto au basilic", "Basil pesto", "volume", None, ("pesto",)),
    ("pruneau", "fruits", "Pruneau", "Dried prune", "mass", None, ("prune séchée",)),
    ("pois_mange_tout", "legumes", "Pois mange-tout frais", "Fresh snow peas", "mass", None, ("pois mange-tout",)),
    ("graine_moutarde", "epices", "Graines de moutarde", "Mustard seeds", "mass", None, ()),
    ("graine_aneth", "epices", "Graines d’aneth", "Dill seeds", "mass", None, ()),
    ("betterave_jaune", "legumes", "Betterave jaune", "Yellow beet", "mass", None, ()),
    ("clou_girofle", "epices", "Clou de girofle", "Clove spice", "mass", None, ()),
    ("sel_celeri", "epices", "Sel de céleri", "Celery salt", "mass", None, ()),
    ("fleur_sel", "epices", "Fleur de sel", "Fleur de sel", "mass", None, ()),
    ("jus_lime", "boissons", "Jus de lime", "Lime juice", "volume", None, ("jus de citron vert",)),
    ("piment_jamaique", "epices", "Piment de la Jamaïque", "Allspice", "mass", None, ()),
    ("pate_miso", "sauces", "Pâte miso", "Miso paste", "mass", None, ("miso",)),
    ("farine_epeautre", "farines", "Farine d’épeautre", "Spelt flour", "mass", None, ()),
    ("fecule_tapioca", "farines", "Fécule de tapioca", "Tapioca starch", "mass", None, ()),
    ("beurre_vegetalien", "huiles", "Beurre végétalien", "Vegan butter", "mass", None, ()),
    ("poivre_noir_grains", "epices", "Grains de poivre noir", "Black peppercorns", "mass", None, ()),
    # FCÉN 2026, aliment 4729 « Sauce, hoisin, prête-à-servir » : 250 ml =
    # 270.27 g, soit 1.081 g/ml.
    ("sauce_hoisin", "sauces", "Sauce hoisin", "Hoisin sauce", "volume", 1.081, ()),
    ("feuille_riz", "pains", "Feuille de riz", "Rice paper", "count", None, ()),
    ("champignon_enoki", "legumes", "Champignon enoki", "Enoki mushroom", "mass", None, ()),
    ("bouillon_miso_vegetalien", "bouillons", "Bouillon miso végétalien", "Vegan miso broth", "volume", None, ()),
    ("graine_celeri", "epices", "Graines de céleri", "Celery seeds", "mass", None, ()),
    ("bouillon_champignon", "bouillons", "Bouillon de champignons", "Mushroom broth", "volume", None, ()),
    ("sauge_moulue", "epices", "Sauge moulue", "Ground sage", "mass", None, ()),
    ("hache_vegetal", "proteines_vegetales", "Haché végétal", "Plant-based ground", "mass", None, ()),
    ("pomme_de_terre_jaune", "legumes", "Pomme de terre à chair jaune", "Yellow-fleshed potato", "mass", None, ()),
    ("pleurote_huitre", "legumes", "Pleurote en huître", "Oyster mushroom", "mass", None, ()),
    ("sauce_toban_djan", "sauces", "Sauce toban djan", "Toban djan", "volume", None, ()),
    ("sauce_barbecue", "sauces", "Sauce barbecue", "Barbecue sauce", "volume", None, ()),
    ("sauce_buffalo", "sauces", "Sauce Buffalo", "Buffalo sauce", "volume", None, ()),
    ("tamari", "sauces", "Sauce tamari", "Tamari", "volume", None, ()),
    ("tomate_passee", "tomates", "Tomates passées", "Strained tomatoes", "volume", None, ()),
    ("zeste_citron", "fruits", "Zeste de citron", "Lemon zest", "mass", None, ()),
    ("noix_melangees", "noix_graines", "Noix mélangées", "Mixed nuts", "mass", None, ()),
    ("epices_italiennes", "epices", "Épices italiennes", "Italian seasoning", "mass", None, ()),
    ("noix_coco_grillee", "noix_graines", "Noix de coco grillée en copeaux", "Toasted coconut flakes", "mass", None, ()),
    ("citronnelle", "herbes", "Citronnelle", "Lemongrass", "mass", None, ()),
    ("sel_marinade", "epices", "Gros sel à marinade", "Pickling salt", "mass", None, ()),
    ("sel_noir_himalayen", "epices", "Sel noir de l’Himalaya", "Himalayan black salt", "mass", None, ("kala namak",)),
    ("bok_choy", "legumes", "Bok choy", "Bok choy", "mass", None, ()),
    ("nouille_ramen_instantanee", "pates", "Nouilles ramen instantanées", "Instant ramen noodles", "mass", None, ()),
    ("algue_nori", "conserves", "Algue nori", "Nori", "count", None, ()),
    ("vin_shaoxing", "boissons", "Vin de cuisine Shaoxing", "Shaoxing cooking wine", "volume", None, ()),
    # FCÉN 2026, aliment 1135 « Sauce, moutarde, brune, prête-à-servir » :
    # 250 ml = 260 g, soit 1.040 g/ml.
    ("moutarde_ancienne", "sauces", "Moutarde à l’ancienne", "Whole-grain mustard", "volume", 1.040, ()),
    # FCÉN 2026, aliment 5354 « Sauce, chili, piments forts, chili, rouges,
    # conserve » : 250 ml = 253.378 g, soit 1.014 g/ml.
    ("sambal_oelek", "sauces", "Sambal oelek", "Sambal oelek", "volume", 1.014, ()),
    # FCÉN 2026, aliment 6195 « Vinaigre, vin rouge » : 250 ml = 252.536 g,
    # soit 1.010 g/ml.
    ("vinaigre_vin_rouge", "sauces", "Vinaigre de vin rouge", "Red wine vinegar", "volume", 1.010, ()),
    # FCÉN 2026, aliment 424 « Huile végétale, sésame » : 250 ml = 230.347 g,
    # soit 0.921 g/ml.
    ("huile_sesame_grillee", "huiles", "Huile de sésame grillé", "Toasted sesame oil", "volume", 0.921, ()),
    ("baguette", "pains", "Baguette", "Baguette", "count", None, ()),
    ("pain_croute", "pains", "Pain croûté", "Crusty bread", "count", None, ()),
    ("noix_coco_rapee", "noix_graines", "Noix de coco râpée", "Grated coconut", "mass", None, ()),
    ("cafe_instantane", "boissons", "Café instantané", "Instant coffee", "mass", None, ()),
    ("assaisonnement_chili", "epices", "Assaisonnement au chili", "Chili seasoning", "mass", None, ()),
    ("ciboulette", "herbes", "Ciboulette", "Chives", "mass", None, ()),
    ("houmous", "conserves", "Houmous", "Hummus", "mass", None, ()),
    ("chapelure_panko", "pains", "Chapelure panko", "Panko breadcrumbs", "mass", None, ()),
    ("pate_tarte", "patisserie", "Pâte à tarte", "Pie crust", "count", None, ()),
    ("coquille_taco", "pains", "Coquille à taco", "Taco shell", "count", None, ()),
]

# Identités supplémentaires justifiées par le corpus francophone Cook.
# Les libellés ``non précisé`` conservent honnêtement l'imprécision de la
# source; ils ne choisissent pas silencieusement une variante.  Comme pour le
# reste du socle, périssabilité, récupération et densité restent inconnues.
INGREDIENTS.extend([
    ("beurre_non_precise", "huiles", "Beurre non précisé", "Unspecified butter", "mass", None, ("beurre",)),
    ("sucre_non_precise", "sucres", "Sucre non précisé", "Unspecified sugar", "mass", None, ("sucre",)),
    # FCÉN 2026, aliment 113 « Lait, liquide, entier, homogénéisé,
    # pasteurisé, 3.25% M.G. » : 250 ml = 257.819 g, soit 1.031 g/ml.
    ("lait_non_precise", "produits_laitiers", "Lait non précisé", "Unspecified dairy milk", "volume", 1.031, ("lait",)),
    # FCÉN 2026, aliment 451 « Huile végétale, canola (colza) » : 250 ml =
    # 230.347 g, soit 0.921 g/ml.
    ("huile_non_precisee", "huiles", "Huile non précisée", "Unspecified cooking oil", "volume", 0.921, ("huile", "huile pour la cuisson")),
    ("poivre_non_precise", "epices", "Poivre non précisé", "Unspecified pepper seasoning", "mass", None, ("poivre", "poivre moulu")),
    ("persil_frais_non_precise", "herbes", "Persil frais non précisé", "Unspecified fresh parsley", "mass", None, ("persil frais", "persil ciselé", "feuilles de persil ciselées")),
    ("cumin_non_precise", "epices", "Cumin non précisé", "Unspecified cumin", "mass", None, ("cumin",)),
    ("basilic_non_precise", "herbes", "Basilic non précisé", "Unspecified basil", "mass", None, ("basilic",)),
    # FCÉN 2026, aliment 4970 « Sauce, moutarde, jaune, prête-à-servir » :
    # 100 ml = 105.25 g, soit 1.053 g/ml.
    ("moutarde_non_precisee", "sauces", "Moutarde non précisée", "Unspecified prepared mustard", "volume", 1.053, ("moutarde", "moutarde préparée")),
    ("cannelle_non_precisee", "epices", "Cannelle non précisée", "Unspecified cinnamon", "mass", None, ("cannelle",)),
    ("poulet_non_precise", "volaille", "Poulet non précisé", "Unspecified chicken", "mass", None, ("poulet", "poulet cuit")),
    ("riz_non_precise", "riz", "Riz non précisé", "Unspecified rice", "mass", None, ("riz",)),
    ("champignon_non_precise", "legumes", "Champignons non précisés", "Unspecified mushrooms", "mass", None, ("champignons",)),
    ("lait_vegetal_non_precise", "boissons", "Lait végétal non précisé", "Unspecified plant milk", "volume", None, ("lait végétal",)),
    ("veau_hache", "veau", "Veau haché", "Ground veal", "mass", None, ()),
    ("boulette_veau_preparee", "veau", "Boulettes de veau préparées", "Prepared veal meatballs", "mass", None, ("boulettes de veau",)),
    ("fusilli", "pates", "Fusillis", "Fusilli", "mass", None, ()),
    ("laitue_iceberg", "legumes", "Laitue iceberg", "Iceberg lettuce", "mass", None, ()),
    ("creme_tartre", "patisserie", "Crème de tartre", "Cream of tartar", "mass", None, ()),
    ("jaune_oeuf", "oeufs", "Jaune d’œuf", "Egg yolk", "count", None, ("jaunes d’œufs",)),
    ("blanc_oeuf", "oeufs", "Blanc d’œuf", "Egg white", "count", None, ("blancs d’œufs",)),
    ("farine_gateaux", "farines", "Farine à gâteaux", "Cake flour", "mass", None, ()),
    ("farine_grillee", "farines", "Farine grillée", "Toasted flour", "mass", None, ("farine grillée pâle",)),
    ("levure_instantanee", "patisserie", "Levure instantanée", "Instant yeast", "mass", None, ()),
    ("moutarde_seche", "epices", "Moutarde sèche", "Dry mustard", "mass", None, ("moutarde en poudre",)),
    # FCÉN 2026, aliment 4970 « Sauce, moutarde, jaune, prête-à-servir » :
    # 100 ml = 105.25 g, soit 1.053 g/ml.
    ("moutarde_jaune", "sauces", "Moutarde jaune", "Yellow mustard", "volume", 1.053, ()),
    ("tomate_cerise", "fruits", "Tomates cerises", "Cherry tomatoes", "mass", None, ("tomate cerise",)),
    ("skyr_vanille", "produits_laitiers", "Skyr à la vanille", "Vanilla skyr", "mass", None, ()),
    ("cereales_riz_souffle", "cereales", "Céréales de riz soufflé", "Puffed rice cereal", "mass", None, ("céréales de riz croquant",)),
    ("prosciutto", "porc", "Prosciutto", "Prosciutto", "mass", None, ()),
    ("guimauve_mini", "patisserie", "Guimauves miniatures", "Mini marshmallows", "mass", None, ()),
    ("pate_brisee", "patisserie", "Pâte brisée", "Shortcrust pastry", "mass", None, ("abaisses de pâte brisée",)),
    ("aile_poulet", "volaille", "Ailes de poulet", "Chicken wings", "mass", None, ()),
    ("aneth_seche", "epices", "Aneth séché", "Dried dill", "mass", None, ()),
    # FCÉN 2026, aliment 5522 « Confiseries, sirop, diététique » : 250 ml =
    # 253.593 g, soit 1.014 g/ml.
    ("aromatisant_eau", "boissons", "Aromatisant liquide pour eau", "Liquid water enhancer", "volume", 1.014, ("aromatisant liquide pour l’eau",)),
    ("baie_genievre", "epices", "Baies de genièvre", "Juniper berries", "mass", None, ()),
    ("pain_levain", "pains", "Pain au levain", "Sourdough bread", "mass", None, ()),
    ("bonbon", "patisserie", "Bonbons", "Candy", "mass", None, ("bonbons au choix",)),
    ("bonbon_petillant", "patisserie", "Bonbons pétillants", "Popping candy", "mass", None, ()),
    ("bouillon_porc", "bouillons", "Bouillon de porc", "Pork broth", "volume", None, ("bouillon de cuisson des jarrets de porc",)),
    ("boulette_boeuf_preparee", "boeuf", "Boulettes de bœuf préparées", "Prepared beef meatballs", "mass", None, ("boulettes de bœuf cuites",)),
    ("bretzel_mini", "pains", "Mini-bretzels", "Mini pretzels", "mass", None, ()),
    ("cannelle_baton", "epices", "Bâtons de cannelle", "Cinnamon sticks", "count", None, ("bâton de cannelle",)),
    ("gnocchi_frais", "pates", "Gnocchis frais", "Fresh gnocchi", "mass", None, ()),
    ("haricot_lima_conserve", "legumineuses", "Haricots de Lima en conserve", "Canned lima beans", "mass", None, ()),
    ("thon_conserve_huile", "poissons", "Thon en conserve dans l’huile", "Canned tuna in oil", "mass", None, ()),
    ("champignon_seche", "legumes", "Champignons séchés", "Dried mushrooms", "mass", None, ()),
    ("chocolat_blanc", "patisserie", "Chocolat blanc", "White chocolate", "mass", None, ()),
    ("chataigne_eau", "conserves", "Châtaignes d’eau", "Water chestnuts", "mass", None, ()),
    # FCÉN 2026, aliment 7617 « Boisson alcoolisée, cidre » : 1 bouteille
    # (341ml) = 341.153 g, soit 1.000 g/ml.
    ("cidre_pomme", "boissons", "Cidre de pomme", "Apple cider", "volume", 1.000, ("cidre",)),
    ("colorant_alimentaire", "patisserie", "Colorant alimentaire", "Food coloring", "volume", None, ()),
    ("lentille_conserve", "legumineuses", "Lentilles en conserve", "Canned lentils", "mass", None, ("conserve de lentilles",)),
    ("bocconcini", "fromages", "Bocconcinis", "Bocconcini", "mass", None, ("minibocconcinis",)),
    ("chocolat_lait", "patisserie", "Chocolat au lait", "Milk chocolate", "mass", None, ()),
    ("creme_champignon_condensee", "conserves", "Crème de champignons condensée", "Condensed mushroom soup", "mass", None, ()),
    ("creme_soya", "boissons", "Crème de soya", "Soy cream", "volume", None, ()),
    ("creme_glace_vanille", "produits_laitiers", "Crème glacée à la vanille", "Vanilla ice cream", "mass", None, ()),
    ("creme_soda", "boissons", "Crème soda", "Cream soda", "volume", None, ("soda mousse",)),
    ("cote_levee_porc", "porc", "Côtes levées de porc", "Pork back ribs", "mass", None, ()),
    ("escalope_veau", "veau", "Escalopes de veau", "Veal cutlets", "mass", None, ()),
    ("escalope_porc", "porc", "Escalopes de porc", "Pork cutlets", "mass", None, ()),
    ("fettuccine", "pates", "Fettuccines", "Fettuccine", "mass", None, ()),
    ("pate_phyllo", "patisserie", "Pâte phyllo", "Phyllo dough", "mass", None, ("feuilles de pâte phyllo",)),
    ("filet_anchois", "poissons", "Filets d’anchois", "Anchovy fillets", "mass", None, ()),
    ("filet_sole", "poissons", "Filet de sole", "Sole fillet", "mass", None, ()),
    ("lard_sale", "porc", "Lard salé", "Salt pork", "mass", None, ("flanc de porc salé",)),
    ("fleur_comestible", "herbes", "Fleurs comestibles", "Edible flowers", "mass", None, ()),
    ("fromage_chevre", "fromages", "Fromage de chèvre", "Goat cheese", "mass", None, ()),
    ("havarti", "fromages", "Havarti", "Havarti cheese", "mass", None, ()),
    ("monterey_jack", "fromages", "Monterey Jack", "Monterey Jack cheese", "mass", None, ()),
    ("pecorino_romano", "fromages", "Pecorino romano", "Pecorino Romano", "mass", None, ()),
    ("provolone", "fromages", "Provolone", "Provolone cheese", "mass", None, ()),
    ("fromage_suisse", "fromages", "Fromage suisse", "Swiss cheese", "mass", None, ()),
    ("fromage_tex_mex", "fromages", "Fromage tex-mex", "Tex-Mex cheese blend", "mass", None, ()),
    ("fromage_velveeta", "fromages", "Fromage fondu de type Velveeta", "Velveeta-style processed cheese", "mass", None, ("fromage Velveeta",)),
    ("feve_germee", "legumes", "Fèves germées", "Bean sprouts", "mass", None, ()),
    ("gomme_xanthane", "patisserie", "Gomme de xanthane", "Xanthan gum", "mass", None, ()),
    # FCÉN 2026, aliment 140 « Lait, concentré, entier, conserve, non dilué,
    # 7,8% M.G. » : 250 ml = 266.272 g, soit 1.065 g/ml.
    ("lait_evapore", "produits_laitiers", "Lait évaporé", "Evaporated milk", "volume", 1.065, ()),
    ("linguine", "pates", "Linguines", "Linguine", "mass", None, ()),
    ("liqueur_orange", "boissons", "Liqueur à l’orange", "Orange liqueur", "volume", None, ()),
    ("olive_kalamata", "conserves", "Olives Kalamata", "Kalamata olives", "mass", None, ()),
    ("origan_frais", "herbes", "Origan frais", "Fresh oregano", "mass", None, ()),
    ("pain_sous_marin", "pains", "Pain à sous-marin", "Submarine roll", "count", None, ("pains à sous-marin",)),
    ("pancetta", "porc", "Pancetta", "Pancetta", "mass", None, ()),
    ("pico_gallo", "sauces", "Pico de gallo", "Pico de gallo", "mass", None, ()),
    ("pilon_poulet", "volaille", "Pilons de poulet", "Chicken drumsticks", "mass", None, ()),
    ("chipotle_adobo", "conserves", "Piments chipotle en sauce adobo", "Chipotle peppers in adobo", "mass", None, ()),
    ("pleurote_erige", "legumes", "Pleurotes érigés", "King oyster mushrooms", "mass", None, ()),
    ("pois_jaune_entier", "legumineuses", "Pois jaunes entiers", "Whole yellow peas", "mass", None, ()),
    ("poivron_melange", "legumes", "Mélange de poivrons", "Mixed bell peppers", "mass", None, ("poivrons de couleurs différentes", "poivrons")),
    ("pate_cari_vert_thai", "sauces", "Pâte de cari vert thaï", "Thai green curry paste", "mass", None, ()),
    ("pate_wonton", "pates", "Pâte à wonton", "Wonton wrappers", "count", None, ("pâte à won-ton",)),
    ("ravioli_fromage", "pates", "Raviolis au fromage", "Cheese ravioli", "mass", None, ()),
    # FCÉN 2026, aliment 2340 « Marinades, relish, sucrée » : 250 ml =
    # 258.876 g, soit 1.036 g/ml.
    ("relish", "sauces", "Relish", "Relish", "volume", 1.036, ()),
    ("rhum_brun", "boissons", "Rhum brun", "Dark rum", "volume", None, ()),
    ("riz_calrose", "riz", "Riz Calrose", "Calrose rice", "mass", None, ()),
    ("rotini", "pates", "Rotinis", "Rotini", "mass", None, ()),
    # FCÉN 2026, aliment 1025 « Sauce, salsa, prête-à-servir » : 250 ml =
    # 273.67 g, soit 1.095 g/ml.
    ("salsa", "sauces", "Salsa", "Salsa", "volume", 1.095, ()),
    # FCÉN 2026, aliment 5364 « Sauce, tomate, sauce chili, bouteille, sel
    # ajouté » : 250 ml = 288.462 g, soit 1.154 g/ml.
    ("sauce_chili", "sauces", "Sauce chili", "Chili sauce", "volume", 1.154, ()),
    # FCÉN 2026, aliment 1030 « Sauce, piments, Tabasco, prête-à-servir » :
    # 250 ml = 239.796 g, soit 0.959 g/ml.
    ("sauce_tabasco", "sauces", "Sauce Tabasco", "Tabasco sauce", "volume", 0.959, ("tabasco",)),
    # FCÉN 2026, aliment 531 « Vinaigrette, mayonnaise, régulière » : 250 ml
    # = 232.46 g, soit 0.930 g/ml.
    ("toum", "sauces", "Sauce toum", "Toum garlic sauce", "volume", 0.930, ("sauce libanaise à l’ail",)),
    ("saucisse_cocktail", "porc", "Saucisses cocktail", "Cocktail sausages", "mass", None, ()),
    ("saucisse_toulouse", "porc", "Saucisses de Toulouse", "Toulouse sausages", "mass", None, ()),
    ("spaghettoni", "pates", "Spaghettonis", "Spaghettoni", "mass", None, ()),
    ("boeuf_faux_filet", "boeuf", "Faux-filet de bœuf", "Ribeye steak", "mass", None, ("steak de faux-filet",)),
    ("epices_mexicaines", "epices", "Épices mexicaines", "Mexican seasoning", "mass", None, ()),
    ("epices_marinade", "epices", "Épices à marinade", "Pickling spice", "mass", None, ()),
    ("epices_steak_montreal", "epices", "Épices à steak de Montréal", "Montreal steak spice", "mass", None, ()),
])

# Alias français exacts qui retirent uniquement une préparation, un état ou une
# formulation régionale; aucune similarité floue n'est promue ici.
RECIPE_ALIASES = {
    "assaisonnement_chili": ("assaisonnement pour chili",),
    "epices_italiennes": ("assaisonnement à l’italienne",),
    "cacao_poudre": ("cacao", "cacao tamisé", "poudre de cacao non sucrée"),
    "fenouil_graines": ("graines de fenouil", "graines de fenouil moulues", "fenouil moulu"),
    "coriandre_fraiche": ("coriandre ciselée", "feuilles de coriandre ciselées"),
    "coriandre_moulue": ("coriandre en poudre",),
    "cari_poudre": ("cari en poudre",),
    "muscade_moulue": ("muscade",),
    "piment_de_cayenne": ("poivre de Cayenne moulu", "c à café de poivre de Cayenne"),
    "piment_jamaique": ("poivre de la Jamaïque moulu",),
    "levure_alimentaire": ("levure nutritionnelle",),
    "pain_tranche_blanc": ("pain blanc à sandwich", "pain blanc sans la croûte"),
    "pois_vert_surgele": ("petits pois surgelés",),
    "flocon_piment": ("piment rouge broyé", "flocons de piment broyé ou plus"),
    "riz_blanc_long": ("riz à grains longs cuit",),
    "huile_vegetale": ("tasse d’huile végétale",),
    "poireau": ("tasse de poireaux",),
    "cassonade": ("tasse de sucre brun",),
    "thon_conserve_eau": ("thon pâle émietté égoutté", "thon blanc en conserve"),
    "haricot_noir_conserve": ("haricots noirs rincés et égouttés", "haricots noirs égouttés"),
}


def normalize_label(value: str) -> str:
    expanded = value.casefold().translate(str.maketrans({"œ": "oe", "æ": "ae"}))
    decomposed = unicodedata.normalize("NFKD", expanded)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def family_rows() -> list[dict]:
    return [
        {
            "id": family_id,
            "name_fr": name_fr,
            "name_en": name_en,
            "description_fr": "Famille descriptive de curation; sans effet de substitution.",
        }
        for family_id, name_fr, name_en in FAMILIES
    ]


def ingredient_rows() -> list[dict]:
    base_units = {"mass": "g", "volume": "ml", "count": "unit"}
    return [
        {
            "id": ingredient_id,
            "family_id": family_id,
            "name": name_fr,
            "unit_kind": unit_kind,
            "base_unit": base_units[unit_kind],
            "perishability": None,
            "salvage_value_cents_per_base_unit": None,
            "density_g_per_ml": density,
        }
        for ingredient_id, family_id, name_fr, _name_en, unit_kind, density, _aliases
        in INGREDIENTS
    ]


def alias_rows() -> list[dict]:
    rows = []
    for ingredient_id, _family, _fr, name_en, _kind, _density, aliases_fr in INGREDIENTS:
        for language, alias in (("en", name_en), *(('fr', item) for item in aliases_fr)):
            rows.append(
                {
                    "canonical_ingredient_id": ingredient_id,
                    "language": language,
                    "alias": alias,
                    "normalized_alias": normalize_label(alias),
                    "source": "catalog-bootstrap",
                    "source_version": "2026-08-12",
                    "confirmed_by": "catalog-bootstrap",
                }
            )
    # Recipe aliases may target an ingredient contributed by the separately
    # curated FCEN batch, not only one declared in INGREDIENTS.  Emitting them
    # in a second pass keeps those reviewed aliases from being silently lost.
    for ingredient_id, aliases_fr in RECIPE_ALIASES.items():
        for alias in aliases_fr:
            rows.append(
                {
                    "canonical_ingredient_id": ingredient_id,
                    "language": "fr",
                    "alias": alias,
                    "normalized_alias": normalize_label(alias),
                    "source": "catalog-bootstrap",
                    "source_version": "2026-08-12",
                    "confirmed_by": "catalog-bootstrap",
                }
            )
    return rows
