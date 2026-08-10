# Menu Optimizer — v1

Application de planification de menus hebdomadaires optimisée par les rabais
d'épicerie. Spécification complète : [`docs/spec.md`](docs/spec.md). Écarts
assumés : [`docs/deviations.md`](docs/deviations.md). Calibration de κ et
u_r justifiée par [`docs/calibration.md`](docs/calibration.md).

**État d'avancement** (ordre de livraison de la spec) : les six étapes
sont livrées — structure, migrations, seeding, spec versionnée ; assertions,
scoring, préfiltrage ; solveur MILP derrière l'interface `MenuSolver` avec
tests à optimum vérifié à la main ; API FastAPI complète (plans persistés,
`commit` reportant les restes vers le garde-manger, liste d'épicerie groupée
par magasin, file de mapping) ; SPA React complète — les cinq écrans, dont la
décomposition du coût en cinq barres signées et l'écran Diagnostic
développeur avec drapeaux modifiables. La demande est encadrée
⌈D⌉ ≤ Σx_r ≤ ⌈D(1+ε)⌉ (D9) ; calibration justifiée dans
`docs/calibration.md` ; l'écran Résultat sépare décaissement et stock déjà
payé (D13).

L'API expose les dix endpoints de la spec sous `/api` (documentation
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
- `web` — SPA React sur <http://localhost:5173> : Ménage (D en direct),
  Génération (infaisabilité explicite), Résultat (menu, épicerie par magasin
  avec itinéraire, cinq barres), Garde-manger, Diagnostic (drapeaux du
  `SolverConfig` modifiables, rapport brut).

Relancer `docker compose up` est sans effet de bord : migrations et seeding
sont idempotents.

### Sans Docker (développement backend)

```bash
cd backend
pip install -e .
export MENU_DATABASE_URL=postgresql+psycopg2://menu:menu@localhost:5432/menu_optimizer
alembic upgrade head
python -m app.seeding.seed --seed-dir ../seed/main   # ou ../seed/toy
uvicorn app.main:app --reload
```

## Activer les mécanismes du solveur un à un

Le solveur (étape 4) expose un `SolverConfig` dont chaque drapeau produit un
modèle valide seul. Le défaut de développement est **tout à `false`, un seul
magasin, `appetence_mode="objective"`** ; on rallume un mécanisme à la fois :

1. `enable_diversity` — sans lui, un menu monotone est **attendu** (c'est la
   démonstration que la contrainte est nécessaire, pas un bug) ;
2. `enable_batch_fixed_cost` — coûts fixes de lot ($\tau^{\text{fixe}}_r$, $\delta_r$) ;
3. `enable_multi_store` — arrêts multiples ($z_s$, coûts de déplacement) ;
4. `enable_time_cost` — valorisation du temps ($\kappa$) ;
5. `enable_pantry_stock` — stock initial ($g_i$) ;
6. `enable_salvage` — valeur résiduelle des surplus ($\sigma_i$, $w_i$).

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

## Données de seed

- `seed/main/` — 23 ingrédients canoniques (3 `unit_kind`, densités pour tous
  les liquides, $\sigma_i$ contrastés : coriandre à 0, riz proche de sa
  borne), 40 recettes partageant des ingrédients, 4 magasins (deux au même
  centre commercial), 83 produits, 4 semaines de prix dont ~70 rabais actifs.
- `seed/toy/` — instance jouet (3 recettes, 4 produits, 1 magasin) dont
  l'optimum sera vérifié à la main par un test à l'étape 4.
- `scripts/generate_seed.py` — générateur déterministe des JSON ; le contrat
  du projet reste les JSON versionnés, jamais le script.

## Arborescence

```
backend/
  app/
    models/       # SQLAlchemy — schémas catalog, market, household, staging
    ports/        # CircularPort, RecipeSourcePort + DTO (contrats stables)
    adapters/     # implémentations JSON v1 des ports
    ingestion/    # atterrissage staging + normalisation vers market
    services/     # units, demand (D9), travel, params, appetence, prefilter,
                  # validation, plan_service (création, épicerie, commit)
    solver/       # SolverConfig, interface MenuSolver, modèle PuLP/CBC
    api/          # routes FastAPI, schémas, dépendances injectables
    seeding/      # commande de seeding idempotente (ports injectables)
  tests/          # pytest — 64 tests : optima manuels, API, substituabilité
  alembic/        # migrations (0001 : schéma initial complet)
docs/             # spec.md (versionnée, intouchée) + deviations.md
frontend/         # SPA Vite + React + TS — cinq écrans, client API typé
seed/main/        # jeu de données principal (JSON versionnés)
seed/toy/         # instance jouet pour le test d'optimum connu
scripts/          # générateur des seeds (outillage, hors application)
```
