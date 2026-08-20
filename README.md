# Menu Optimizer — v1

Application de planification de menus hebdomadaires optimisée par les rabais
d'épicerie. Spécification complète : [`docs/spec.md`](docs/spec.md). Écarts
assumés : [`docs/deviations.md`](docs/deviations.md). Calibration de κ et
u_r justifiée par [`docs/calibration.md`](docs/calibration.md).

**État d'avancement** (ordre de livraison de la spec, puis pilote produit) :
les six étapes de la spec sont livrées — structure, migrations, seeding,
spec versionnée ; assertions, scoring, préfiltrage ; solveur MILP derrière
l'interface `MenuSolver` (six termes d'objectif — voir D19,
`docs/deviations.md`) avec tests à optimum vérifié à la main ; API FastAPI
complète (plans persistés, verrouillage/remplacement/réoptimisation,
finalisation post-génération, liste d'épicerie groupée par magasin, file de
mapping) ; SPA React complète — trois onglets (Planification, Ménage,
Paramètres). La demande est encadrée ⌈D⌉ ≤ Σx_r ≤ ⌈D(1+ε)⌉ (D9) ; calibration
justifiée dans `docs/calibration.md`. Le garde-manger à quantité suivie
d'origine a été retiré et remplacé par les essentiels (staples, pure
appartenance ménage/ingrédient) — voir `CLAUDE.md` pour l'historique complet
du pilote.

L'API expose quatorze endpoints sous `/api` (documentation
interactive : `/docs`). Le solveur, le scorer et les ports d'acquisition sont
injectés — des tests de substituabilité (`tests/test_substitutability.py`)
prouvent qu'une implémentation factice de chacune des quatre interfaces
(`MenuSolver`, `AppetenceScorer`, `CircularPort`, `RecipeSourcePort`)
traverse le système sans qu'aucune implémentation concrète ne soit atteinte —
c'est la garantie exécutable de la promesse v1 : brancher un vrai scraper et
1000 vraies recettes sans toucher au solveur, à l'API ni au front-end.

## Lancer

```bash
docker compose up --build
```

Une seule commande démarre les trois services :

- `db` — PostgreSQL 16, quatre schémas (`catalog`, `market`, `household`, `staging`) ;
- `api` — applique les migrations Alembic, exécute le seeding idempotent
  depuis `seed/main`, puis sert FastAPI sur <http://localhost:8000>
  (santé : `GET /api/health`) ;
- `web` — SPA React sur <http://localhost:5173> : Planification (génération,
  infaisabilité explicite, menu + épicerie par magasin avec itinéraire),
  Ménage (essentiels, membres, préférences — D en direct), Paramètres
  (drapeaux du `SolverConfig` modifiables, rapport de diagnostic brut).

Relancer `docker compose up` est sans effet de bord : migrations et seeding
sont idempotents.

### Sans Docker (pile complète)

Sur une machine sans Docker, les trois services se démarrent à la main. Il faut
un PostgreSQL joignable — service local ou distant — puis, depuis la racine du
dépôt, deux terminaux.

**Back-end** :

```bash
cd backend
pip install -e .
export MENU_DATABASE_URL=postgresql+psycopg2://menu:menu@localhost:5432/menu_optimizer
alembic upgrade head
python -m app.seeding.seed --seed-dir ../seed/main   # ou ../seed/toy
uvicorn app.main:app --reload --port 8000
```

**Front-end**, dans un second terminal :

```bash
cd frontend
npm install
npm run dev
```

Le proxy `/api` du serveur Vite vise `http://127.0.0.1:8000` par défaut, donc
les deux commandes ci-dessus suffisent. `API_URL` le redirige ailleurs — c'est
ce que fait la pile compose, qui doit viser le service `api` de son réseau.

**Si le port 8000 est déjà pris.** Sous Windows, la plage réservée par
Hyper-V/WSL peut contenir 8000 : le port n'est pas occupé par un serveur, il est
interdit, et `uvicorn` échoue sur `WinError 10013` (« accès à un socket
interdit par ses permissions »). `netstat -ano | findstr :8000` le confirme.
Choisir un autre port et le dire aux deux côtés :

```bash
uvicorn app.main:app --reload --port 8001          # back-end
API_URL=http://127.0.0.1:8001 npm run dev          # front-end
```

`WEB_PORT` déplace de même le port du serveur Vite.

## Activer les mécanismes du solveur un à un

Le solveur (étape 4) expose un `SolverConfig` dont chaque drapeau produit un
modèle valide seul. Le défaut de développement est **tout à `false`, un seul
magasin, `appetence_mode="objective"`** ; on rallume un mécanisme à la fois :

1. `enable_diversity` — sans lui, un menu monotone est **attendu** (c'est la
   démonstration que la contrainte est nécessaire, pas un bug) ;
2. `enable_batch_fixed_cost` — coûts fixes de lot ($\tau^{\text{fixe}}_r$, $\delta_r$) ;
3. `enable_multi_store` — arrêts multiples ($z_s$, coûts de déplacement) ;
4. `enable_time_cost` — valorisation du temps ($\kappa$) ;
5. `enable_staples` — un essentiel du ménage est évalué au prix historique
   le plus bas dans l'objectif, jamais au décaissement réel ;
6. `enable_salvage` — valeur résiduelle des surplus ($\sigma_i$, $w_i$) ;
7. `enable_perishable_penalty` — pénalise, plutôt que de simplement ne pas
   créditer, le surplus d'un ingrédient périssable (D19, `docs/deviations.md`).

Chaque résolution retourne le rapport de diagnostic complet : statut et
temps de résolution, valeur de chaque terme de l'objectif séparément,
paramètres surchargeables effectifs avec leur provenance (profil ou
`SolverConfig`), contraintes saturées, comptes du préfiltrage, surplus
valorisés, et — en cas d'infaisabilité — la liste des assertions passées et le
dernier drapeau activé (IIS indisponible avec CBC, voir D11).

## Où brancher le vrai scraper

Le point de branchement est **unique et déjà en place** :

- Contrat : `backend/app/ports/circular.py` (`CircularPort.fetch_week`) et les
  DTO de `backend/app/ports/dto.py` (`RawOfferDTO`).
- Implémentation v1 : `backend/app/adapters/json_circular.py` (lit
  `seed/*/raw_offers.json`).
- Cheminement : le scraper produit des `RawOfferDTO` → `land_offers` les fait
  atterrir **bruts** dans `staging.raw_offer` → `normalize_offers` résout via
  `market.product_mapping` et upserte `market.price`
  (`backend/app/ingestion/normalize.py`).

Remplacer l'adaptateur JSON par un scraper réel ne touche ni au staging, ni à
la normalisation, ni (plus tard) au solveur, à l'API ou au front-end. Même
principe pour le catalogue de recettes : `RecipeSourcePort.load_all()` /
`json_recipe_source.py`.

## Catalogues hebdomadaires Maxi + Super C

`scripts/run_weekly_catalogues.py` démarre simultanément la capture de **Maxi
7552** et des rayons publics de **Super C Neufchâtel (magasin 640, 4545 boul.
de l'Auvergne)**. Après la réussite des deux sources, il rapproche les produits
aux slugs canoniques puis fait passer les offres par `staging` et
`normalize_offers` dans une seule transaction.

Les rayons et les pages de rabais hebdomadaires des deux bannières sont des
listes éditables dans `config/catalogues.json`. Chaque passage complet capture
explicitement le Centre des offres Maxi et la grille « Toutes les promotions »
de Super C, en plus des rayons. Le manifeste et le rapport inscrivent les
`deal_targets`; une ancienne capture sans ces cibles ne peut pas être rejouée
comme complète. Les listes livrées couvrent fruits, légumes, viandes,
poissons, produits laitiers, œufs, ingrédients de garde-manger et ingrédients
surgelés, ainsi que les catégories mixtes nécessaires aux recettes importées :
boulangerie, charcuterie, aliments végétariens, boissons, bières et vins. Même
si une catégorie mixte contient un produit composé, seuls les rapprochements
canoniques non ambigus deviennent des `market.product`. Les snacks et plats
composés restent exclus par leur identité. Les produits au poids conservent le
prix unitaire et l'incrément publiés; ils ne sont plus rejetés ni transformés
en emballage fictif.
Le rapprochement porte sur tout le catalogue canonique; le sous-ensemble
référencé par `seed/main/recipes.json` n'est calculé que comme mesure de
couverture et sera filtré plus tard par le solveur.
Les promotions sont conservées, y compris lorsque Super C marque un rabais
sans afficher de prix régulier barré.

La période est dérivée automatiquement selon la circulaire jeudi-mercredi.
Maxi utilise une fenêtre Edge visible et un profil séparé sous `data/`; ce mode
est nécessaire parce que le site refuse actuellement Edge sans interface. Si
le site demande une vérification, la fenêtre reste ouverte le temps configuré
pour la compléter. Il ne faut ni fermer cette fenêtre ni utiliser le profil
Edge personnel. Maxi espace ses pages de 4 à 5 secondes. Super C est limité à
une requête toutes les 10 à 12 secondes et rejoue avec
attente sur HTTP 429 et erreurs transitoires; un passage complet prend donc
plusieurs minutes. Le client respecte aussi les deux formes de `Retry-After`
(secondes ou date HTTP). Pour une prévisualisation courte, sans base de
données :

```powershell
.\.venv\Scripts\python.exe scripts\run_weekly_catalogues.py `
  --maxi-max-pages 1 `
  --superc-category fruits-et-legumes/fines-herbes-fraiches --max-pages 1
```

Pour le lancement complet, installer le backend, démarrer PostgreSQL,
appliquer les migrations et le seed, puis double-cliquer `run_catalogues.cmd`
(ou lancer la commande suivante). La fenêtre de commande lance Maxi et Super C
ensemble et affiche leur progression indépendamment :

```powershell
.\.venv\Scripts\python.exe scripts\run_weekly_catalogues.py --apply
```

La rotation de proxys HTTP/HTTPS est facultative et ne se déclenche qu'après
une erreur transitoire. Chaque proxy conserve ses propres cookies et refait la
sélection du magasin avant de reprendre. Les adresses — et surtout leurs
identifiants — ne doivent pas être ajoutées à `config/catalogues.json` : les
charger depuis la variable d'environnement configurée, sous forme de liste
JSON. Sous PowerShell :

```powershell
$env:SOUSCHEF_SUPERC_PROXIES='["http://proxy-1.example:8080","https://proxy-2.example:8443"]'
.\.venv\Scripts\python.exe scripts\run_weekly_catalogues.py --apply
```

Sans cette variable, le collecteur utilise simplement la connexion directe.
Les délais, la variation aléatoire, le nombre de reprises, le délai maximal et
le nom de la variable sont configurables dans `config/catalogues.json`.

Un passage complet met aussi à jour `data/catalogue-registry/maxi.json` et
`superc.json`, les listes maîtresses indexées par identifiant commercial et
UPC. Les produits qui disparaissent deviennent inactifs, sans perdre leur
décision. Les fichiers `*-canonical-gaps.json` isolent les produits actifs sans
aucun candidat canonique; les passages limités ne modifient jamais ces listes.

Les captures structurées et le rapport détaillé sont écrits sous `data/` et
ignorés par Git. Chaque source écrit dans un dossier `run-*` isolé et ne pose
son manifeste `_complete.json` qu'après la dernière page; une exécution
partielle ne peut donc pas être rejouée par erreur. Les options
`--reuse-maxi-captures` et `--reuse-superc-captures` rejouent la dernière
exécution complète de la semaine, qui est aussi validée contre la période.
En complément, `data/catalogue-registry/maxi-indexed-titles.json` conserve un
instantané daté des titres publiquement indexés. La commande
`scripts/curate_maxi_indexed_titles.py` les classe vers le canon et produit
`config/maxi-title-match-overrides.json`. Ces règles par titre sont rejouées
sur les futurs UPC capturés; elles ne constituent ni une capture de prix ni une
garantie d'exhaustivité pour un magasin donné.

La couverture et les prix de recettes se vérifient sans PostgreSQL. Les deux
commandes suivantes produisent respectivement les causes exclusives de lacune
et les devis (coût consommé, décaissement, économies et confiance) :

```powershell
.\.venv\Scripts\python.exe scripts\audit_recipe_pricing_coverage.py `
  --week 2026-W33 --superc-root data\catalogue-captures\superc\2026-W33 `
  --minimum-complete-recipes 28

.\.venv\Scripts\python.exe scripts\quote_recipes.py `
  --week 2026-W33 --superc-root data\catalogue-captures\superc\2026-W33 `
  --json-output data\catalogue-reports\recipe-quotes-2026-W33.json
```

L'API expose les mêmes calculs par `GET /api/recipe-quotes`; la sémantique des
montants est fixée dans `docs/adr-recipe-pricing-semantics.md`.

## Données de seed

- `seed/main/` — 1 066 ingrédients canoniques répartis dans 31 familles, avec
  1 220 alias français/anglais et 766 références FCÉN auditées. Périssabilité
  et valeur de récupération restent à `null`; 6 densités déjà établies sont
  conservées. Le catalogue actif contient 40 recettes de démonstration et 121
  recettes réelles validées provenant de Ricardo, Bon pour toi et La cuisine
  de Jean-Philippe. Les 83 produits de démonstration utilisent le sous-ensemble
  historique de 23 ingrédients.
- `seed/toy/` — instance jouet (3 recettes, 4 produits, 1 magasin) dont
  l'optimum sera vérifié à la main par un test à l'étape 4.
- `scripts/generate_seed.py` — générateur déterministe des JSON ; le contrat
  du projet reste les JSON versionnés, jamais le script. Il conserve les
  recettes réelles de `seed/main/imported_recipes.json` à chaque régénération.

### Recettes importées depuis Cook

`scripts/import_cook_recipes.py` convertit le corpus français du projet Cook
vers le format de `seed/main/recipes.json`. Une recette entre dans le catalogue
actif seulement si ses portions, ses bornes de lot, son temps et toutes ses
identités et quantités d'ingrédients sont connus. Les décisions manuelles,
équivalences vérifiées, estimations déclarées et omissions hors calcul sont
versionnées dans `config/cook_recipe_curation.json`. Les desserts sont exclus
dans `data/recipe-import-review/cook-recipes-excluded.json`; la file
`cook-recipes-review.json` est actuellement vide.

```powershell
.\.venv\Scripts\python.exe scripts\import_cook_recipes.py
```

## Importer les candidats d'ingrédients FCÉN 2026

Le [Fichier canadien sur les éléments nutritifs 2026](https://open.canada.ca/data/en/dataset/1b6139bd-ed7e-4043-bc28-ff00e10f3109)
sert de registre externe bilingue à curer; ses 5 993 aliments ne sont jamais
copiés directement dans le catalogue canonique.

Après `alembic upgrade head`, télécharger l'archive officielle puis lancer,
depuis `backend/` :

```bash
python -m app.ingestion.cnf --archive ../data/cnf_fcen_all-files-data_2026.zip
```

L'import est idempotent, calcule le SHA-256 de l'archive et conserve les noms
français et anglais dans `staging.cnf_food_candidate`. Les groupes clairement
hors recette sont mis en quarantaine par statut, jamais supprimés. Un rejeu
actualise la copie source sans écraser les décisions de curation. Les alias
approuvés et les liens vers les identifiants externes ont leurs propres tables
dans `catalog`. Le flux hors ligne `app.ingestion.ingredient_curation` les
peuple seulement après une décision humaine explicite. Pour examiner une
ligne puis appliquer un manifeste versionné :

```bash
python -m app.ingestion.ingredient_curation preview --source-version 2026 --food-code 1234
python -m app.ingestion.ingredient_curation apply --manifest ../data/curation-riz.json
```

Le manifeste choisit `attach_existing`, `create_variant` ou `exclude`, avec
un auteur et une justification. Un nom/alias normalisé identique bloque la
création; une forte similarité exige un acquittement explicite et n'entraîne
jamais de fusion automatique. Le format est détaillé dans
[`docs/ingredient-curation.md`](docs/ingredient-curation.md).

Le lot versionné courant est produit par une passe conservatrice et
reproductible :

```bash
python scripts/refine_cnf_catalog.py --archive data/cnf_fcen_all-files-data_2026.zip
python scripts/generate_catalog.py
```

Le lot courant accepte 738 codes : 591 nouvelles identités et 147
rattachements au canon existant. Parmi les créations, 333 ont un nom similaire
à un canon existant et conservent explicitement les identifiants comparés dans
`acknowledged_similar_ids`; 11 autres cas revus sont exclus comme mélanges ou
fractions nutritionnelles. Les formes cuites, assaisonnées, composées ou trop
spécifiques ne sont pas promues. Le seed conserve pour chaque acceptation le
crosswalk et l'événement d'audit associés.

Le socle généraliste versionné est généré par
`python scripts/generate_catalog.py`. Il représente des identités achetables,
jamais des marques ou formats, et préserve tous les identifiants utilisés par
les recettes et produits de démonstration.

La sélection de la source, ses limites et le détail des colonnes françaises
sont documentés dans
[`docs/ingredient-database-research.md`](docs/ingredient-database-research.md).

## Arborescence

```
backend/
  app/
    models/       # SQLAlchemy — schémas catalog, market, household, staging
    ports/        # CircularPort, RecipeSourcePort + DTO (contrats stables)
    adapters/     # implémentations JSON v1 des ports
    ingestion/    # atterrissage, normalisation et curation hors HTTP
    services/     # units, demand (D9), travel, params, appetence, prefilter,
                  # validation, planning/household/catalog/offer_resolution
                  # (modules applicatifs — routes.py n'appelle qu'eux,
                  # jamais SQLAlchemy directement, y compris pour le
                  # mapping produit depuis D18)
    solver/       # SolverConfig, interface MenuSolver, modèle PuLP/CBC
    api/          # routes FastAPI (transport HTTP seulement), schémas,
                  # dépendances injectables
    seeding/      # commande de seeding idempotente (ports injectables)
  tests/          # pytest — 141 tests : optima manuels, API, substituabilité,
                  # modules applicatifs (planning/household/catalog)
  alembic/        # migrations (0001 : schéma initial complet)
docs/             # spec.md (versionnée, intouchée) + deviations.md
frontend/         # SPA Vite + React + TS — trois onglets, client API typé
seed/main/        # jeu de données principal (JSON versionnés)
seed/toy/         # instance jouet pour le test d'optimum connu
scripts/          # générateur des seeds (outillage, hors application)
```
