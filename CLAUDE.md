# CLAUDE.md — Menu Optimizer

Repère pour sessions futures. Vérifié par exécution réelle (PostgreSQL 16 en
docker, pas de simulation) le 2026-08-10 — voir « État vérifié » en bas.
Spec d'origine : [`docs/spec.md`](docs/spec.md) (verbatim, ne jamais modifier).
Écarts assumés : [`docs/deviations.md`](docs/deviations.md).

**Avant toute session de vérification, lance la garde contre la dérive de
profil (D16) :**
```bash
cd backend
python -m app.seeding.check_profile_drift --seed-dir ../seed/main
```
Sort en erreur (code 1) si `household_profile` en base a divergé de
`seed/main/household.json`. Une session qui teste ou calibre contre un
profil drifted (ça s'est produit : `min_distinct_recipes`,
`time_value_cents_per_hour`, `diet_flags`, `taste_preferences`,
`max_prep_time_per_meal_h` ont tous dérivé dans la base de dev courante)
tire des conclusions qui ne correspondent à rien de documenté.

## Architecture en couches

```
1. Ingestion  — ports d'acquisition, exécution en lot, jamais dans une requête HTTP
2. Données    — repositories/models SQLAlchemy, aucune logique métier
3. Services   — appetence, prefilter, demand, validation, params, travel, units, solver
4. API        — FastAPI, expose des résultats déjà calculés
5. Front-end  — SPA React
```

**Règle stricte : aucune couche ne saute par-dessus la suivante.** L'API ne
touche jamais SQLAlchemy directement pour de la logique métier (elle appelle
`services/`) ; les services ne lisent jamais `staging` (c'est le rôle
d'`ingestion/normalize.py` de le vider vers `market`) ; le solveur ne parle
jamais à la base — il reçoit un `ProblemData` déjà chargé
(`services/problem_data.py`). Si tu es tenté de faire une requête SQL depuis
`api/routes.py` ou de lire `household_profile` directement dans
`solver/model.py`, c'est que tu es en train de sauter une couche — arrête-toi.

Arborescence (`backend/app/`) :
```
ports/        CircularPort, RecipeSourcePort + DTO — contrats stables
adapters/     implémentations JSON v1 des ports (seul point qu'un vrai scraper remplace)
ingestion/    normalize.py — staging → market, idempotent
models/       SQLAlchemy — schémas catalog, market, household, staging
services/     appetence, prefilter, demand (D9), validation, params, travel,
              units, needs, problem_data, planning/household/catalog/
              offer_resolution (modules applicatifs — voir « Refactor
              architecture » et « D18 » ci-dessous)
solver/       config.py (SolverConfig), port.py (interface MenuSolver + DTOs
              résultat), model.py (implémentation PuLP/CBC)
api/          routes.py (transport HTTP seulement, appelle les modules
              applicatifs de services/), schemas.py, deps.py (injection)
seeding/      seed.py — commande idempotente, ports injectables
```

## Refactor architecture — modules applicatifs (2026-08-10)

`api/routes.py` contournait la couche services (requêtes SQLAlchemy directes,
mutations, calcul de coût attribué) malgré son en-tête l'affirmant. Corrigé :
la logique a été déplacée dans trois modules de `services/` —
`planning.py` (ex-`plan_service.py` ; `generate_plan`/`get_plan`/
`commit_plan`), `household.py` (`get_profile`/`update_profile`/`get_pantry`/
`update_pantry`), `catalog.py` (`search_recipes`/`list_stores`). Chaque
module expose des DTO typés (dataclasses) et des exceptions typées
(`PlanNotFound`, `PlanNotCommittable`, `ProfileNotFound`,
`UnknownIngredientError`) que `routes.py` traduit en `HTTPException` — c'est
la seule logique qui reste dans les routes. Au moment de ce refactor,
`get_unmapped`/`post_map` restaient une exception volontaire (D15, alors non
résolu) ; **ce n'est plus le cas depuis D18** (ci-dessous) — `routes.py`
n'importe plus `sqlalchemy` ni `..models` nulle part.

**Décision de conception à retenir** : les fonctions de module gardent
`session: Session` en premier paramètre explicite (pas de session ouverte en
interne). Une session interne casserait `tests/db_fixtures.py::api_client`,
qui fonctionne en overridant la dépendance FastAPI `get_session` pour
injecter une session de test partagée par requêtes d'un même test — un
module ouvrant sa propre session n'aurait plus cette prise et se
connecterait à la mauvaise base. Détail dans
`docs/architecture-refactoring-plan.md` (qui suggérait des interfaces sans
paramètre `Session` — corrigé en pratique lors de l'implémentation).

**Vérification : 82/82 tests passés contre PostgreSQL réel**, dont
`tests/test_api.py` **non modifié** et 7 nouveaux tests de module directs
(`tests/test_planning_module.py`, `tests/test_household_module.py`,
`tests/test_catalog_module.py`). Vérifié en deux temps : le bac à sable de
la session de refactor n'avait initialement pas accès à PostgreSQL/Docker
(63 tests sans base passaient, le reste sautait proprement) ; l'utilisateur
a ensuite démarré sa base pendant la même session, ce qui a permis un run
complet réel — un seul défaut trouvé, dans un des nouveaux tests
(`test_household_module.py` comparait une valeur `Decimal` sérialisée à
`"6"` au lieu de `"6.000"`), corrigé, aucun défaut dans le code de
production. Point de méthode confirmé au passage : lancer `pytest`
(sans `-m`) depuis un environnement conda `base` sans venv dédié échoue sur
`ModuleNotFoundError: No module named 'tests'` même après `pip install -e
".[dev]"` — utiliser un venv isolé (`python3 -m venv .venv`) et `python -m
pytest`, comme documenté dans « Sans Docker » ci-dessous.

**Hors périmètre, volontairement** (voir `docs/architecture-refactoring-plan.md`) :
D15/`OfferResolutionModule` (traité séparément, voir D18 ci-dessous), refactor
du solveur (excepté le renommage de labels PuLP fait en D18, voir plus bas),
fonctionnalités du pilote produit (`docs/product-pilot.md`).

## D18 — Résolution de D15 : `product_mapping` clé sur `(store_id, raw_text)` (2026-08-11)

Session dédiée, demandée explicitement par l'utilisateur (« démarrer D15 »).
Trois défauts corrigés, détaillés dans `docs/deviations.md` (D18) : (1)
`normalize_offers` ne consultait jamais `product_mapping` (le bug documenté
par D15) ; (2) `post_map` mettait à jour `staging.raw_offer` directement
depuis une route HTTP, contournant l'ingestion en lot ; (3) la clé
`raw_text` seule (relevée par l'utilisateur en revue du plan) confondait des
produits différents d'une bannière à l'autre.

`market.product_mapping` résout maintenant vers `product_id` (pas seulement
`canonical_ingredient_id`), clé sur `(store_id, raw_text)` (migration
`9a2f6e1c4b7d`, avec une garde qui refuse de supprimer les lignes
existantes si `confirmed_by IS NOT NULL` y figure). Nouveau module
`services/offer_resolution.py` (`list_unresolved`/`attach_existing_product`/
`create_and_attach_product`), qui ne touche jamais `staging.raw_offer` —
c'est `normalize_offers`, en lot, qui reconsulte la table et résout les
offres historiques et futures. `solver/model.py` nomme désormais ses
variables/contraintes PuLP depuis les clés de substitution (`p.id`/`s.id`),
pas `external_key` (instable par nature, D15) — sauf le tri du bris de
symétrie, règle métier documentée (`docs/spec.md`), laissé inchangé.

**Vérifié contre PostgreSQL réel** : cycle de migration
upgrade/downgrade/upgrade propre ; **86/86 tests passés, 0 sauté** (82
avant ce chantier + 4 nouveaux tests directs dans
`tests/test_offer_resolution_module.py`, dont un qui rejoue le scénario
exact décrit comme cassé dans D15 et confirme qu'il ne l'est plus) ;
`tests/test_solver_toy.py`/`tests/test_solver_flags.py` inchangés dans
leurs assertions malgré le renommage des variables PuLP.

**Hors périmètre, volontairement** (le document de D15 lui-même le met en
garde) : appariement flou/heuristique automatique `raw_text → produit`
(exige de vraies données scrapées pour être conçu sans risquer une
hypothèse fausse), écran de curation front-end dédié, flux de rejet
(`MappingStatus.rejected`).

## Pilote — verrouillage, remplacement, réoptimisation expliquée (2026-08-11)

Première tranche du pilote produit (`docs/product-pilot.md`) construite sur
`PlanningModule`. Un seul mécanisme sert deux usages : **verrouiller** =
fixer `x_r` exactement à la valeur du plan précédent (`SolverConfig.
locked_recipe_servings`, nouvelle contrainte inconditionnelle
`solver/model.py::_add_locked_recipes` — dict vide = no-op, pas de nouveau
`enable_*`) ; **remplacer une recette** = verrouiller toutes les autres
recettes du plan courant + exclure celle visée (et ses variantes d'échelle
sœurs, D16) + réoptimiser — la bande de demande D9 force alors le solveur à
ne redistribuer que la part laissée vacante, un remplacement local sans code
séparé. « Réoptimisation plus large » = même appel avec seulement les
recettes explicitement verrouillées par l'utilisateur.

`services/prefilter.py::prefilter_recipes` gagne `force_keep_ids`/
`exclude_ids` (une recette verrouillée qui ne passe plus les filtres durs —
ex. nouvelle allergie déclarée entre deux générations — n'est **pas**
repêchée ; `services/planning.py::reoptimize_plan` le détecte et lève
`RecipeNotLockableError` **avant** d'appeler le solveur, jamais un statut
`Infeasible` muet). Nouvelle route `POST /api/plan/{id}/reoptimize`,
`ReoptimizationResult` (menu ajouté/retiré + delta du poste achats,
`None` si infaisable). Portée volontairement restreinte : la bascule
automatique « local → plus large si le résultat reste mauvais » (seuil 5 $/
10 % du produit-pilote) devient un choix manuel à deux boutons, pas une
détection + escalade automatique — jugement UX honnête pour une première
tranche, pas une simplification cachée.

**Vérifié contre PostgreSQL réel** : **93/93 tests passés, 0 sauté** (86
avant ce chantier + 7 nouveaux — un test solveur qui pince `x_r` sur
l'instance jouet, 5 tests directs de `reoptimize_plan`, 1 test API bout en
bout), migration inchangée (pas de nouvelle migration ce chantier),
`tsc -b`/`vite build` du front-end propres. **Non vérifié** : interaction
réelle dans un navigateur (pas d'affichage/automatisation navigateur
disponible dans cette session) — à faire manuellement via `docker compose
up` avant de considérer l'écran Résultat terminé, en particulier
l'enchaînement verrou → réoptimiser → nouveau plan affiché.

## Lancer / tester / seeder

```bash
docker compose up --build      # api applique migrations + seed puis sert ; web sur :5173
```

Sans Docker :
```bash
cd backend
pip install -e ".[dev]"        # corrigé en D14 — fonctionne depuis, vérifié en venv propre
export MENU_DATABASE_URL=postgresql+psycopg2://menu:menu@localhost:5432/menu_optimizer
alembic upgrade head
python -m app.seeding.seed --seed-dir ../seed/main   # ou ../seed/toy
uvicorn app.main:app --reload
```

Tests (nécessitent un PostgreSQL réel — `db_fixtures.py` crée/migre
`menu_test` puis seed le jouet une fois par session ; sinon `pytest.skip`
propre) :
```bash
cd backend
MENU_TEST_DATABASE_URL=postgresql+psycopg2://menu:menu@localhost:5432/menu_test pytest
```

Activer les mécanismes du solveur un à un (défaut dev : tout `False`, un seul
magasin) : `enable_diversity` → `enable_batch_fixed_cost` →
`enable_multi_store` → `enable_time_cost` → `enable_pantry_stock` →
`enable_salvage`. Chaque drapeau seul doit produire un modèle résoluble
(`tests/test_solver_flags.py`). **Exception** : `enable_variant_exclusion`
(D16) est à `True` par défaut, même en configuration minimale — ce n'est pas
un mécanisme d'optimisation à activer un à un, c'est une contrainte
d'intégrité (voir INVARIANTS).

Brancher un vrai scraper : implémenter `CircularPort` / `RecipeSourcePort`
(`backend/app/ports/`), câbler dans `seeding/seed.py` ou un futur job batch —
ne touche ni `staging`, ni `normalize.py`, ni le solveur, ni l'API.
`product_mapping` (D18, `docs/deviations.md`) résout maintenant vers un
produit précis, clé sur `(store_id, raw_text)`, et une confirmation via
`services/offer_resolution.py` est réellement reconsultée par
`normalize_offers` au passage suivant. **Reste hors périmètre** :
l'appariement automatique `raw_text → produit` (aucune heuristique/NLP —
toute confirmation reste manuelle) et l'écran de curation front-end ; à
concevoir contre de vraies données scrapées quand elles existeront, pas
avant (même mise en garde que D15 à l'origine).

## INVARIANTS — ne jamais « simplifier »

- **Surplus : inégalité `w_i ≤ approvisionnement − besoin`, jamais `≥` ni `=`.**
  Avec `≥`, le solveur gonfle `w_i` librement et l'objectif part à `−∞` ; `≤`
  suffit car l'optimum le sature naturellement. (`solver/model.py::_add_surplus`)
- **Big-M agrégé sur la demande totale, jamais sur une seule recette.**
  `M_ps = ⌈D_max · max_r(â_marg+â_fixe) / v_p⌉` où `D_max` est la demande
  agrégée (borne haute D9) — une borne fondée sur une seule recette rendrait
  infaisables des paniers légitimes sans que le solveur ne le signale.
  (`solver/model.py::_big_m`)
- **Marge de 0,8 sur σ_i, évaluée à l'exécution contre la base, pas au seed.**
  `σ_i ≤ 0,8 · min_{p,s} c_ps(1+t_p)/v_p`. Le générateur de seed calibre σ_i
  pour que ce soit vrai *par construction* au moment de générer les JSON, mais
  l'assertion est réévaluée à **chaque résolution** contre les prix réellement
  chargés (`services/validation.py::validate_problem`, assertion 1) — un vrai
  scraper apportera ses propres prix, et c'est cette assertion, pas la
  calibration du seed, qui garde le problème borné.
- **Demande encadrée `⌈D⌉ ≤ Σx_r ≤ ⌈D(1+ε)⌉`, pas une égalité.** L'égalité de
  la spec est infaisable dès que `D = n_repas·Σρ_h` n'est pas entier (écart
  D9, décidé au point de contrôle — n'est *pas* une simplification, c'est une
  extension assumée du domaine faisable). (`services/demand.py`)
- **Filtre de temps du préfiltrage = contrainte de session, pas d'amortissement
  par portion.** `τ_fixe_r + β_r·τ_marg_r ≤ max_prep_time_per_meal` (temps du
  plus petit lot possible). κ arbitre le temps moyen dans l'objectif ; le
  filtre dur ne fait qu'écarter les séances trop longues (D11). Test
  discriminant : `test_prep_time_is_a_session_constraint`.
- **Au plus une variante par famille de plat : `Σ_{r∈famille} δ_r ≤ 1`
  (D16).** Les variantes d'échelle (`<id>`/`<id>_familial`) sont deux
  segments d'une même courbe de coût non linéaire pour un seul plat, pas
  deux plats — sans cette contrainte, le plafond de part x_r ≤ α·D et le
  compte de diversité Σδ_r ≥ R_min se contournent en fractionnant un même
  plat entre ses deux recettes (vérifié en direct avant correctif : 49 % du
  menu de référence était un seul plat sous deux id différents). La
  pénalité de répétition inter-plans compare aussi `dish_family_id`, pas
  `recipe.id`, pour la même raison. (`solver/model.py::_add_variant_exclusion`,
  `services/appetence.py`, `services/dish_family.py`)
- **Montants en `Decimal` ou cents entiers, jamais en flottant.** Colonnes
  `*_cents_cad` (entiers), sauf `salvage_value_cents_per_base_unit`
  (`Numeric(14,6)` — sub-cent au gramme, D4). Les flottants de PuLP ne
  servent qu'à la résolution interne ; le rapport de diagnostic recalcule
  tout en `Decimal` depuis la solution entière (`solver/port.py::ObjectiveTerms`).
- **Chemin port → staging → normalisation, jamais de raccourci.** Même
  l'adaptateur JSON v1 passe par `land_offers` (atterrissage brut,
  `staging.raw_offer`, idempotent via empreinte sha256) puis
  `normalize_offers` (résolution vers `market.price`). C'est ce chemin, et
  lui seul, qu'un vrai scraper empruntera sans changement.
  (`ingestion/normalize.py`)
- **Interfaces déclarées remplaçables restent injectées, jamais codées en
  dur.** `MenuSolver`, `AppetenceScorer`, `CircularPort`, `RecipeSourcePort`.
  Un scorer `RuleBased` codé en dur dans le solveur a déjà régressé une fois
  (calibration de l'étape 4) — c'est exactement ce que
  `tests/test_substitutability.py` interdit désormais (vérifié par moi : casser
  l'injection dans `solver/model.py` fait échouer
  `test_appetence_scorer_is_substitutable` — le piège fonctionne réellement).
- **Conversion masse↔volume : jamais de défaut à densité = 1,0.** Absence ou
  nullité de `density_g_per_ml` lève `MissingDensityError` explicite.
  (`services/units.py::convert_qty`)
- **`substitutable` sur `recipe_ingredient` n'a aucune sémantique en v1.**
  Colonne présente pour éviter une migration future ; ni le solveur, ni le
  préfiltrage, ni l'API ne doivent la lire. Ne pas « profiter » de la colonne
  pour une optimisation rapide — ce serait inventer une sémantique hors spec.
- **`household_profile` est la source de vérité des paramètres surchargeables**
  (`max_store_visits`, `min_distinct_recipes`, `max_share_per_recipe`,
  `demand_slack_epsilon`). La résolution passe *uniquement* par
  `services/params.py::resolve_effective_params` — n'ajoute pas de lecture
  croisée profil/`SolverConfig` ailleurs.

## Écarts assumés (D1–D16) — détail dans `docs/deviations.md`

- **D1/D2** — étapes 1–2 livrent un `/api/health` et un squelette front pour
  que `docker compose up` démarre ; l'API et la SPA complètes arrivent aux
  étapes 5–6 (levé).
- **D3** — colonnes renommées avec unité explicite (`price_cents_cad`, etc.) ;
  correspondance aux symboles de la spec en docstrings.
- **D4** — `salvage_value_cents_per_base_unit` en `Numeric(14,6)`, pas en
  entier (sub-cent au gramme) ; la spec autorise `Decimal`.
- **D5** — clés primaires slugs texte réservées à `catalog` (curé) ;
  `market.store`/`product`/`price` utilisent des clés de substitution + un
  `external_key` (veto partiel au point de contrôle).
- **D6** — `seed/main/` et `seed/toy/`, chargeables par la même commande de
  seeding via `--seed-dir`.
- **D7** — `payload_fingerprint` (sha256) ajouté à `staging.raw_offer` pour un
  atterrissage idempotent au rejeu.
- **D8** — générateur de seed : prix réguliers déterministes par (magasin,
  produit), positionnement par bannière, σ_i calibré par construction contre
  les prix générés.
- **D9** — demande encadrée `⌈D⌉ ≤ Σx_r ≤ ⌈D(1+ε)⌉` au lieu de l'égalité
  stricte (invariant ci-dessus).
- **D10** — `taste_preferences` (JSONB) ajouté à `household_profile`, requis
  par le scoring d'appétence mais absent du schéma de la spec.
- **D11** — sémantiques précisées au solveur : filtre de temps = session,
  effets de `enable_batch_fixed_cost`/`enable_pantry_stock` sur les besoins
  (signalés dans `flag_effects`), magasin unique déterministe,
  linéarisation du rabais centre commercial, `mip_gap_attained = None`
  (CBC via PuLP n'expose pas la borne duale).
- **D12** — table `household.plan` ajoutée : l'API de la spec (`GET
  /api/plan/{id}`, `POST .../commit`) suppose des plans persistés que le
  modèle de données de la spec ne définissait pas.
- **D13** — diagnostic distingue décaissement et stock de garde-manger déjà
  payé (`pantry_consumed_value_cents`) — sinon l'écran Résultat afficherait un
  gain inexistant après un commit.
- **D14** — `pyproject.toml` : `[tool.setuptools.packages.find] include =
  ["app*"]` ajouté, corrige `pip install -e .` qui échouait faute de
  découverte de paquets explicite (trouvé et corrigé après livraison, session
  de vérification du 2026-08-10).
- **D15** — au moment de cette session (2026-08-10, D16), OPEN DESIGN non
  résolu : `product_mapping` inerte, `normalize_offers` ne la lisait jamais.
  **Résolu depuis, en D18** (section « D18 » plus haut dans ce fichier,
  détail dans `docs/deviations.md`) — laissé ici tel quel comme trace de
  l'état au moment de cette session historique.
- **D16** — exclusion mutuelle des variantes d'échelle du même plat
  (`dish_family_id`, `enable_variant_exclusion` défaut `True`) : sans elle,
  deux recettes du même plat (`<id>`/`<id>_familial`) contournaient le
  plafond de part et gonflaient le compte de diversité ; la pénalité de
  répétition inter-plans comparait aussi des `recipe.id` bruts au lieu de
  `dish_family_id`. Corrigé et vérifié (voir INVARIANTS et « État vérifié »
  ci-dessous). Inclut une garde contre la dérive de `household_profile`
  (`check_profile_drift`, à lancer en tête de session — voir en haut de ce
  fichier).

## État vérifié (2026-08-10, contre PostgreSQL 16 réel, pas de simulation)

- **Suite de tests : 71 tests passés, 0 échec, 0 sauté** (64 + 7 ajoutés pour
  D16 : 3 sur l'exclusion mutuelle, 3 sur la garde de dérive, 1 sur la
  pénalité de répétition inter-familles). README pas encore remis à jour
  pour ce chiffre — à corriger à la prochaine passe documentaire. Autres
  chiffres audités contre le code et les JSON de
  seed (150 recettes tronquées, R_min=4/α=0,3, f_sortie=4,00 $/f_marg
  formule, comptes 23/40/4/83 de `seed/main`, 3/3/1/4 de `seed/toy`, les
  quatre `external_key` de magasin de `docs/calibration.md`) : tous
  cohérents, aucun autre chiffre périmé trouvé. Le point d'ancrage κ=15 $/h
  de `docs/calibration.md` (4 recettes, 37-41 portions) est directement
  couvert par `test_main_seed_all_flags_on`, qui passe ; le reste du balayage
  κ∈{0,5,10,20} n'a pas été rejoué indépendamment (non demandé, coûteux à
  revérifier point par point).
- **Migration `upgrade head` → `downgrade base` → `upgrade head`** sur base
  vierge : propre. 4 schémas / 12 tables recréés à l'identique après le
  cycle complet.
- **Seeding rejoué deux fois** sur base fraîchement migrée : deuxième passe
  rapporte explicitement « 0 nouvelles offres » en staging, et les 11 tables
  vérifiées ont un compte de lignes strictement identique avant/après
  (23/40/218/4/83/1128/1128/83/1/3/3). Idempotence confirmée, pas juste
  affirmée.
- **`tests/test_substitutability.py` teste réellement quelque chose** : j'ai
  cassé l'injection du scorer dans `solver/model.py` (appel direct de
  `RuleBasedAppetenceScorer` au lieu de `self._scorer_factory`) —
  `test_appetence_scorer_is_substitutable` échoue immédiatement sur le piège
  monkeypatch (`AssertionError: RuleBasedAppetenceScorer atteint malgré
  l'injection...`). Revert fait, 64/64 de nouveau vert.
- **`pip install -e .` corrigé (D14)** : `[tool.setuptools.packages.find]
  include = ["app*"]` ajouté à `backend/pyproject.toml`. Revérifié en venv
  propre, hors Docker : install éditable → `alembic upgrade head` →
  seeding → `uvicorn app.main:app` (santé `200 {"status":"ok"}`) → suite
  pytest complète (64 passés), tout par ce chemin exact.
- **D16 confirmé puis corrigé, pas seulement supposé.** Sur le plan de
  référence (seed principal, tous drapeaux actifs, profil canonique), avant
  correctif : `chili_lentilles` (8) et `chili_lentilles_familial` (10)
  retenues ensemble, 18/37 portions (49 %) sur un seul plat, chacune sous le
  plafond α·⌈D(1+ε)⌉ = 12,3 individuellement. Après correctif (même
  reseeding canonique) : 4 recettes = 4 plats distincts
  (`distinct_dish_families == distinct_recipes == 4`), le solveur choisit
  systématiquement la variante familiale (économie d'échelle dominante à ce
  volume), `saturated_constraints["diversite"]` liste les 4 contraintes
  `exclusion_variante_*` actives. Le test structurel
  (`tests/test_variant_exclusion.py`) prouve que la contrainte contraint
  réellement : R_min=2 sur une famille à 2 variantes devient infaisable avec
  le drapeau actif, redevient faisable en le désactivant explicitement.
- **Garde de dérive vérifiée en conditions réelles** : lancée contre la base
  de dev du conteneur courant, `check_profile_drift` a détecté 5 champs
  drifted (pas seulement `min_distinct_recipes`, repéré à la main dans la
  session précédente). Déterminé — pas supposé — que `docs/calibration.md`
  reflète le profil canonique du seed et pas cette dérive : reproduction à
  l'identique (menu, portions, total) en réensemençant une base neuve avec
  le profil canonique complet ; la base drifted produit un menu différent.
  Drift non corrigé en base (hors périmètre demandé — seule la garde a été
  ajoutée).
- **`product_mapping.confirmed_by` : défaut confirmé, plus grave qu'un simple
  écrasement.** Scénario testé en direct (offre au `product_external_key`
  volontairement irrésolvable, comme le sera une vraie offre scrapée) :
  1. l'offre atterrit `unmapped`, une ligne `product_mapping` est créée
     (`canonical_ingredient_id=None`) ;
  2. confirmation manuelle (simulant `POST /api/ingredients/map`) : la ligne
     `product_mapping` passe à `canonical_ingredient_id='riz'`,
     `confirmed_by='anton@test'` — **elle n'est jamais écrasée** ensuite
     (`on_conflict_do_nothing`/`do_update` sur `raw_text` la protège) ;
  3. une **nouvelle** offre arrive la semaine suivante avec le **même**
     `raw_text` (rejeu hebdomadaire réaliste d'un scraper sur un produit déjà
     mappé à la main) : elle retombe `unmapped`, et **aucune ligne
     `market.price` n'est créée** pour elle.
  Cause : `ingestion/normalize.py::normalize_offers` résout le produit
  uniquement via `known_products.get(payload["product_external_key"])` — il
  ne consulte **jamais** la table `product_mapping`, ni en lecture ni pour
  créer/retrouver un `market.product`. Le mapping confirmé est donc bien
  préservé, mais **fonctionnellement mort** : le travail manuel ne profite à
  aucune offre future, seule l'offre déjà traitée au moment de la
  confirmation en bénéficie. Pire : même en corrigeant cette lecture, la
  table `product_mapping` ne résout que jusqu'à `canonical_ingredient_id` —
  pas jusqu'à un `market.product` précis (marque, format) — donc une
  correction complète demande un mécanisme supplémentaire, pas juste un
  lookup ajouté. Non corrigé (demande explicite : rapporter, pas corriger).

## Évaluation franche

**Solide.** La séparation ports/staging/normalisation est réelle et vérifiée
par un test qui piège activement les implémentations concrètes — ce n'est pas
une promesse en l'air, la substituabilité fonctionne à l'exécution, pas
seulement au niveau des types. Les assertions de validité (§ spec) sont
implémentées et testées une par une, y compris dans leurs cas limites
(`test_assertion_6_alpha_check_is_ge_not_gt`). La gestion Decimal/cents est
cohérente de bout en bout jusqu'au rapport de diagnostic. Le traitement de
D9 (encadrement de la demande) est le bon type d'écart : documenté, motivé,
avec ses conséquences propagées listées explicitement (assertion 6, capacité,
Big-M) plutôt que corrigées en silence ailleurs.

**Fragile ou limite.**
- Le `print()` de debug dans `demand.py` (toujours présent, non corrigé —
  hors mandat de cette session) est le genre de chose qui aurait dû être
  attrapée par une revue avant l'étape 5 — ce n'est pas grave en soi, mais
  c'est un signal que le dernier passage sur les services de base (avant que
  le solveur et l'API ne s'en emparent) n'a pas été relu ligne à ligne.
- `pip install -e .` était cassé (corrigé en D14) et contredisait directement
  le README censé le documenter. Personne n'avait testé le chemin « sans
  Docker » tel qu'il était écrit — seul le chemin Docker (qui contourne le
  problème en n'installant jamais le paquet) avait dû être exercé.
- Le gap MIP réel n'est jamais connu (`mip_gap_attained = None`, D11) : la
  garantie d'optimalité repose entièrement sur la confiance dans le statut
  « Optimal » de CBC. Défendable et documenté, mais ça reste un point aveugle
  si CBC ment un jour sur son statut.
- Le générateur de seed (`scripts/generate_seed.py`) calibre σ_i *contre les
  prix qu'il vient de générer* pour que l'assertion 1 passe par construction.
  C'est correct et assumé (D8), mais ça veut dire que le jeu de données
  principal est structurellement incapable de faire échouer l'assertion 1 —
  la seule couverture réelle de cette assertion en échec vient des tests
  unitaires synthétiques (`test_assertion_1_salvage_bound_at_runtime_prices`),
  jamais du seed « réaliste ». Si un futur scraper apporte un vrai prix
  cassé, ce sera la première fois que l'assertion est testée en conditions
  réelles.

**Insuffisamment testé, à ma connaissance après une seule passe.**
- Aucun test de charge/volume : la troncature à 150 recettes et le Big-M
  agrégé sont conçus pour ~1000 recettes, mais rien dans `tests/` ne construit
  un problème à cette échelle pour vérifier le temps de résolution ou la
  stabilité numérique du Big-M à cette taille.
- Le chemin `product_mapping` semi-manuel (`GET /api/ingredients/unmapped`,
  `POST /api/ingredients/map`) est couvert côté API
  (`test_recipes_stores_and_mapping_endpoints`), mais ce test ne vérifie que
  la réponse HTTP et l'écriture de la ligne `product_mapping` — jamais
  qu'une résolution *suivante* en profite. **Confirmé défectueux** (voir
  « État vérifié ») : `normalize_offers` ignore complètement
  `product_mapping` en lecture. C'est un défaut sérieux pour la promesse
  « brancher un vrai scraper sans toucher au reste » — le mapping semi-manuel
  qu'exige la spec pour ce cas précis ne fait rien d'utile aujourd'hui. À
  corriger avant de brancher un vrai scraper, pas seulement « à creuser ».
- Je n'ai testé la migration et le seeding que sur une base vierge à un seul
  cycle ; je n'ai pas vérifié la robustesse d'Alembic à un downgrade partiel
  (une révision intermédiaire) ni la seed idempotence après une modification
  manuelle des données (ex. un prix édité à la main puis un rejeu du seed —
  écrase-t-il silencieusement l'édition ?).

Rien de ce que j'ai vérifié ne contredit les affirmations de fond de
`docs/deviations.md` ou `docs/calibration.md`. Mise à jour : le
contournement du plafond de diversité par les variantes d'échelle
(soupçonné, puis confirmé en direct, puis corrigé — D16) était réel et
structurel, pas un artefact d'un seul plan. Il n'a été repéré ni par les 64
tests de la session précédente ni par une lecture des docs — seule une
demande explicite de vérifier ce mécanisme précis l'a fait apparaître. Ça
corrobore la leçon de méthode ci-dessous plutôt que de la contredire.

## Leçon de méthode pour les sessions futures

Le `print()` de debug dans `demand.py` et le `pyproject.toml` cassé ont tous
les deux survécu à 64 tests verts — aucun des deux n'a jamais fait échouer
la moindre assertion. Ce n'est pas une coïncidence : `pytest` s'exécute
toujours depuis `backend/` avec le code source déjà sur `sys.path`, donc la
suite passe qu'on installe le paquet ou non — elle ne peut structurellement
pas détecter un `pip install -e .` cassé. Et un `print()` ne fait échouer
qu'un test qui vérifie explicitement la sortie standard, ce qu'aucun ne fait.
**Une suite verte ne couvre que ce qu'elle a été écrite pour vérifier — pas
les chemins que la documentation décrit mais que personne n'a fait échouer
exprès.** Le défaut sur `product_mapping.confirmed_by` est du même ordre :
`test_recipes_stores_and_mapping_endpoints` vérifie que l'endpoint répond et
écrit une ligne, jamais qu'un rejeu ultérieur en tient compte.

Conséquence pour toute session future sur ce projet : ne pas se contenter de
lancer `pytest` et lire « N passed ». Pour toute affirmation du README ou de
`docs/` qui décrit un chemin d'exécution (une commande à taper, un
comportement attendu au rejeu, une garantie d'idempotence, un mécanisme
« prévu pour plus tard »), vérifier s'il existe un test qui échouerait si ce
chemin était cassé — et si non, l'exercer une fois à la main avant de le
tenir pour acquis, comme cette session l'a fait pour l'installation éditable
et pour `product_mapping`.
