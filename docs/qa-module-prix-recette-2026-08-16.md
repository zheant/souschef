# QA/QC — module de calcul du prix d'une recette (2026-08-16)

Périmètre : `backend/app/services/recipe_costing.py`, `recipe_quotes.py`,
`recipe_quality.py`, `recipe_pricing_coverage.py`, la route
`GET /api/recipe-quotes`, `scripts/quote_recipes.py`, et le rapport produit
`data/catalogue-reports/recipe-quotes-2026-W33.json` (161 recettes, 130
complètes, 130 déclarées « sans réserve », 364 produits, magasin `superc_640`).

Méthode : lecture du code, 19 sondes d'exécution directes contre le module pur,
et analyse statistique du rapport W33. Les 17 tests du module passent
(`test_recipe_costing.py`, `test_recipe_quality.py`,
`test_recipe_pricing_coverage.py`). Chaque constat ci-dessous a été reproduit,
aucun n'est déduit de la seule lecture.

---

## A. Défauts de correction

### A1 — `GET /api/recipe-quotes` est mort dans la pile Docker

`recipe_quotes._RULES_PATH` vaut `Path(__file__).parents[3] / "config" /
"ingredient-procurement-rules.json"`. Dans le conteneur, le fichier est à
`/srv/app/services/recipe_quotes.py`, donc `parents[3]` = `/` et le chemin visé
est `/config/ingredient-procurement-rules.json`. Or `backend/Dockerfile` fait
`COPY . .` depuis `./backend` seulement, et `docker-compose.yml` ne monte que
`./seed`. Le fichier n'existe pas dans l'image : premier appel de la route →
`FileNotFoundError` → 500.

Aggravant : `config/` n'est pas versionné (`git status` le donne en `??`). La
seule source des règles d'approvisionnement — dont la règle `essential` de
l'eau — vit hors du dépôt et hors de l'image.

`_load_supply_rules()` relit par ailleurs le fichier à chaque requête, sans
cache.

### A2 — Un prix de 0 est une offre valide et gagne la sélection

Le filtre de candidats est `offer.price_cents_cad >= 0`. Une offre à 0 remporte
donc systématiquement `min(candidates, key=_taxed_unit_price)` et le devis
sort `status: complete`, `consumed_cost_cents: 0.00`, `confidence: exact`.

```
sonde F : offres [free 0c/1000g, real 500c/1000g] pour 100 g
       -> consommé 0.00, produit « free », décaissement 0.00
```

C'est exactement ce que l'ADR interdit : « Une donnée absente rend le devis
incomplet ; elle ne devient jamais un coût nul. » Le garde-fou existe aujourd'hui
dans `maxi_capture.py` (`if price is None or price <= 0`), mais l'invariant est
déclaré au niveau du module de coût, et le module ne le tient pas. Toute source
de prix future (base de données, second scraper) rouvre le trou.

### A3 — Les « économies » comparent la promo à elle-même, pas à l'alternative

`regular_comparable_cents` applique le prix régulier **au panier choisi sous
promo**. Si la promo rend le gros format le moins cher, on compare au prix
régulier du gros format, jamais au format que l'on aurait réellement acheté hors
promo.

```
sonde 2 : besoin 700 g
  gros  800 g à 3,00 $ (régulier 20,00 $, en promo)
  petit 800 g à 4,00 $
  -> décaissement 3,00 $, « régulier » 20,00 $, économies 17,00 $
     alors que l'alternative réelle hors promo coûte 4,00 $ (économie : 1,00 $)
```

Corollaire : si `regular_price_cents_cad < price_cents_cad` (donnée fautive), les
économies sortent négatives et sont publiées telles quelles (sonde 12 : −4,00 $).

### A4 — Un ingrédient entièrement couvert par le garde-manger rend le devis incomplet

Quantité requise nulle après déduction du stock, aucun produit au marché → la
recette entière passe `incomplete` et `consumed_cost_cents` devient `None`, alors
qu'il n'y a rien à chiffrer.

```
sonde 6 : besoin 10 g, pantry 50 g, aucune offre
       -> status incomplete, incomplete_ingredients ('epice_rare',), required 0
```

Le paramètre `pantry` n'est d'ailleurs jamais transmis par la façade SQL
`quote_recipes` — seul l'appel direct au module pur l'expose.

### A5 — Les règles d'approvisionnement ne résolvent qu'un seul saut, et seulement vers un produit

`_quote_recipe` remplace l'ingrédient par `rule.source_ingredient_id` puis exige
un produit commercial pour cette source. Deux cas légitimes échouent :

- `derived → essential` : `bouillon → eau` (eau = `essential`) → `incomplete`.
- `derived → derived` : chaîne de deux conversions → `incomplete`.

`recipe_pricing_coverage.audit_recipe_pricing_coverage` lit les **mêmes** règles
avec une boucle de point fixe explicitement conçue pour les chaînes. Les deux
modules ne s'accordent donc pas sur l'ensemble des recettes chiffrables : l'audit
de couverture annonce une couverture que le calcul de prix ne sait pas livrer.

### A6 — Égalité de prix unitaire : la sélection dépend de l'ordre des offres

La ligne d'achat départage explicitement (`_checkout_cents`, prix unitaire, puis
`product_external_key`). La ligne de consommation, non : `min(candidates,
key=_taxed_unit_price)` retourne le premier minimum rencontré.

```
sonde B : A (1000 g / 5,00 $) et B (2000 g / 10,00 $), même prix unitaire
  ordre (A, B) -> produit A     ordre (B, A) -> produit B
```

`quote_recipes` construit `price_stmt` sans `ORDER BY` : l'ordre de PostgreSQL
n'est pas garanti, donc deux appels identiques peuvent citer deux produits
différents. L'ADR promet qu'« l'utilisateur peut remonter d'un total vers chaque
quantité, conversion, produit, magasin » — une preuve non reproductible n'est pas
une preuve.

---

## B. Sémantique qui produit des nombres trompeurs

### B1 — Le nombre principal est valorisé à un prix que le ménage ne paiera jamais

Le coût consommé prend le meilleur prix unitaire du magasin, tous formats
confondus. C'est un choix documenté, mais son effet mesuré sur le rapport W33 :

- **532 lignes** d'ingrédient sont valorisées sur un produit **autre** que celui
  que la ligne d'achat achète réellement.
- Revalorisées au prix du produit effectivement acheté, les 130 recettes
  complètes passent de **2 011,67 $ à 2 210,36 $, soit +9,9 %**.
- Écarts individuels jusqu'à ×2,24 (`riz_frit_oeuf` 2,24 $ → 5,01 $),
  ×1,99 (`tortilla_espagnole`), ×1,94 (`pates_fraiches`).

Exemple lisible (`pommes_de_terre_tapees`) : consommation valorisée sur le sac de
**50 lb** à 0,088 $/100 g, panier composé d'un sac de 3 lb à 0,22 $/100 g. La carte
recette affiche le prix de gros ; la liste d'épicerie facture le prix de détail.

L'ADR fait du coût consommé « la valeur principale d'une carte recette ». Il est
biaisé à la baisse de façon systématique et non signalée.

### B2 — Un seul niveau de confiance pour deux nombres de fiabilité différente

L'ADR dit : « le coût consommé reste calculable au prix unitaire, mais le
décaissement autonome est signalé `estimated` ». L'implémentation prend le pire
niveau de **toutes** les lignes, achats compris, et l'applique au devis entier.

```
sonde 3 : bœuf au poids sans incrément
  quote.confidence = estimated   alors que   ingredients[0].confidence = exact
```

Le test `test_variable_weight_without_increment_is_declared_estimated` verrouille
ce comportement — c'est la spec qui n'est pas tenue, pas un accident.

### B3 — Un « décaissement autonome » peut exiger deux magasins

Rien n'impose un magasin unique. La route API laisse `store` vide par défaut.

```
sonde 1 : riz chez maxi_7552, bœuf chez superc_640
       -> stores ('maxi_7552', 'superc_640'), décaissement 12,48 $
```

Aucun coût de déplacement, aucun signal. Le rapport W33 n'expose pas le problème
parce qu'il n'a tourné que sur `superc_640` (364/364 produits).

### B4 — `servings` ne change rien pour 121 recettes sur 161

Les recettes importées portent toutes leurs quantités dans
`qty_fixed_per_batch_base_unit`, avec `qty_marginal_per_serving_base_unit = 0` :
**0 des 121 recettes importées** a une composante marginale. `quote_recipes(...,
servings=8)` renvoie donc la même nourriture, le même panier et le même total ;
seule la division par portion change. Un appelant qui demande « le prix de cette
recette pour 8 » obtient une réponse fausse sans le moindre avertissement.

### B5 — Fenêtre de validité incohérente possible

`valid_from = max(...)`, `valid_to = min(...)` sur des offres aux fenêtres
disjointes produit une fenêtre vide, publiée sans signal.

```
sonde 5 : offres 13–19 août et 20–26 août
       -> valid_from 2026-08-20, valid_to 2026-08-19
```

### B6 — Un `sale_mode` inconnu dégrade en silence

Toute valeur autre que `fixed_package` et sans incrément tombe dans la branche
« acheter exactement le besoin » + `estimated`, au lieu de lever.

```
sonde 4 : sale_mode="mode_inconnu", besoin 150 g d'un format 1000 g
       -> décaissement 75 c, purchase_units 0,15
```

### B7 — `purchase_units` n'est jamais arrondi ni quantifié

220 lignes d'achat non entières dans le rapport W33, dont **46** avec une
représentation du type `0.006000006000006000006000006000` (ail au poids). La ligne
« acheter 3 g d'ail » est en outre peu crédible en caisse.

### B8 — Une exigence nulle produit une ligne d'achat à 0

`quantity = 0` crée quand même un `PurchaseCostLine` à 0 unité / 0,00 c, qui
remontera dans la liste d'épicerie.

---

## C. Résultats invraisemblables du rapport W33

### C1 — De la bière vendue comme du miel, dans 8 recettes

`superc:628190004730` — « Bière forte rousse au miel et aux épices », Bilboquet,
473 ml, 4,49 $, taxée à 14,975 % — est approuvée sous `canonical_ingredient_id =
miel` et déclarée `package_qty_in_base_unit = 473` (la conversion miel ml→g de
0,698113 n'est pas appliquée). Elle apparaît comme **ligne d'achat du miel dans 8
recettes** (`ailes_de_poulet_buffalo`, `boulettes_teriyaki_au_poulet`,
`figues_roties`, `marinade_a_steak`, …).

À 1,09 c/g contre 0,84 c/g pour le vrai miel, elle perd la valorisation mais
gagne le panier (5,16 $ contre un pot de 1 kg à 5,85 $). Elle n'apparaît donc que
côté épicerie — ce qui explique qu'elle ait survécu à la revue précédente, qui
lisait surtout les coûts consommés. Une boisson alcoolisée est dans la liste
d'épicerie sous le nom d'un ingrédient de base.

### C2 — Une demi-caisse de figues comptée comme une figue

`superc:033383402567` — « Demi caisse de figues fraîches », 9,99 $ —
`package_qty_in_base_unit = 50`, avec pour provenance « CNF 2026, aliment 1711 :
1 figue moyenne = 50 g ». L'équivalence pièce→masse a été appliquée au titre d'un
format de gros. Conséquence : figues à **200 $/kg** ; 350 g demandés → 7
demi-caisses → **69,93 $ sur un décaissement de 91,26 $**, et 36,62 $/portion —
2ᵉ recette la plus chère du rapport, **zéro réserve**.

### C3 — La recette la plus chère du rapport n'a aucune réserve

`salade_aux_peches_facon_panzanella`, 2 portions, **55,71 $/portion**,
`quality_flags: []`. Quantités source :

| ingrédient | quantité (2 portions) | plausible ? |
|---|---|---|
| `roquette` | 2 000 g | non — 1 kg/portion de roquette |
| `basilic_frais` | 375 g | non — 18 barquettes de 21 g = 50,22 $ |
| `peche` | 900 g | douteux |
| `pain_tranche_blanc` | 5 g | non — c'est « 5 tranches » recopié en grammes |

Le pain à 5 g est exactement le bug « 1 g voulait dire 1 unité » déjà traité en
session du 2026-08-13, et il échappe à la garde parce que
`MIN_PLAUSIBLE_BODY_QUANTITY = 5` est comparé avec `<` strict : 5 n'est pas
inférieur à 5. Même famille de défaut chez `sandwich_fondant_au_thon` :
`pain_levain = 2 200 g` pour 2 portions (1,1 kg de pain au levain par personne),
9,65 $/portion, zéro réserve.

### C4 — `recipe_quality` n'a aucune borne supérieure

Le module ne détecte que les quantités **trop petites**, et seulement pour
`BODY_FAMILIES`. Résultat : « 130 devis complets, 130 sans réserve » alors que les
deux recettes les plus chères du rapport sont l'une et l'autre pilotées par des
quantités manifestement fausses. Cinq lignes dépassent 500 g/portion sans
signalement (`pain_levain` 1 100, `roquette` 1 000, `cote_levee_porc` 575,
`pomme_de_terre` 568, `epinard` 500), et les herbes/épices n'ont aucune règle du
tout (basilic à 187 g/portion).

Un seuil unique en grammes ne peut pas trancher : la borne utile est une norme
par famille et **par portion**, pas une constante.

### C5 — Identités de produit encore approximatives côté panier

- « Mayonnaise chimichurri » (Heinz, 340 ml) achetée comme `mayonnaise` dans
  **10 recettes**.
- `poivre_noir` valorisé sur « Poivre noir **en grains** 575 g » là où la recette
  veut du moulu ; le panier achète bien du moulu — les deux nombres ne décrivent
  pas le même produit.
- `fromage_bleu` : consommation sur « Fromage bleu danois 2 × 175 g », achat sur
  « Fromage à pâte demi-ferme persillée 100 g ».
- Vin et bière de cuisson (`vin_rouge_sec`, `vin_blanc_sec`, `biere_blonde`)
  portent la taxe de 14,975 % : correct au sens fiscal, à confirmer comme voulu.

### C6 — Les essentiels n'existent pas dans le module de prix

Une seule règle `essential` est déclarée (`eau`). Tout le reste s'achète en entier
au décaissement autonome. Nombre de recettes achetant plus de **20 fois** le
besoin :

| ingrédient | recettes | exemple |
|---|---|---|
| `sel_table` | 27 | 1,25 g requis → sac de 1 kg à 1,99 $ (**×800**) |
| `huile_olive` | 19 | |
| `huile_vegetale` | 13 | |
| `farine_tout_usage` | 12 | |
| `feuille_laurier` | 10 | |
| `jus_citron`, `poivre_noir` | 8 chacun | |

Multiple de surplus médian, toutes lignes confondues : **2,65×**. 18 recettes ont
un décaissement supérieur à 5× leur coût consommé. Cas extrême : `trempette
ranch`, 1 portion, **7,80 $ consommés contre 41,81 $ à décaisser** — 14 achats,
dont 11 condiments et épices de garde-manger.

Le concept d'essentiels existe déjà côté solveur (`household.staple`,
`enable_staples`). Le module de prix ne le lit pas et le fichier de règles ne le
reproduit pas.

### C7 — Ciboulette à 362 $/kg

Barquette de 5,5 g à 1,99 $. `pommes_de_terre_tapees` demande 62,5 g → **12
barquettes = 23,88 $**, soit 66 % du décaissement de la recette, et 96 % du coût
consommé (22,61 $ sur 23,60 $). Deux défauts se composent : une quantité de
recette probablement fausse et un plan d'achat qui empile douze micro-formats
sans jamais le signaler.

### C8 — Portions déclarées non représentatives

`trempette_ranch` est déclarée **1 portion** pour ~500 ml de trempette : le prix
par portion n'a pas de sens et `yield_not_in_servings` ne se déclenche pas faute
de preuve dans `tags.servings_source`. La règle repose entièrement sur la présence
de cette preuve ; son absence est traitée comme une absence de problème.

---

## D. Couverture de test

17 tests passent, mais ils ne couvrent que le module pur.

- **`recipe_quotes.quote_recipes` n'a aucun test** : la fusion des confiances
  (`price.pricing_confidence` vs `product.quantity_confidence`), le filtre de date
  `valid_from <= on_date <= valid_to`, le filtre magasin, le chargement du fichier
  de règles et son chemin (A1) ne sont exercés nulle part.
- Aucun test pour : prix à 0 (A2), économies contre l'alternative hors promo (A3),
  ingrédient couvert par le garde-manger (A4), chaîne de règles (A5), déterminisme
  en cas d'égalité (A6), panier multi-magasins (B3), `sale_mode` inconnu (B6),
  fenêtre de validité incohérente (B5).
- `app/services/__init__.py` importe toute la couche services : `import
  app.services.recipe_costing` échoue sans SQLAlchemy installé, malgré la
  docstring « Ce module ne connaît ni SQLAlchemy ni HTTP » et la promesse de l'ADR
  de comparer la couverture « sans PostgreSQL ».

---

## Ordre de traitement proposé

1. **A1** — la route est cassée en production ; verser `config/` dans git et dans
   l'image (ou charger les règles depuis la base).
2. **C1, C2** — retirer la bière de `miel` et corriger le format de la demi-caisse
   de figues ; ce sont des faits faux publiés, pas des approximations.
3. **A2, A3, A4** — trois invariants du module que le module ne tient pas ; chacun
   se corrige en quelques lignes et se verrouille par un test.
4. **C4** — donner une borne supérieure à `recipe_quality`, par portion et par
   famille, sans quoi « sans réserve » reste une affirmation non fondée.
5. **B1, B2** — décider si le coût consommé doit rester valorisé au format le
   moins cher ; sinon publier les deux nombres avec leur confiance propre.
6. **C6** — importer les essentiels du ménage dans les règles d'approvisionnement.
7. **B4** — refuser (ou signaler) `servings` sur une recette sans composante
   marginale.
