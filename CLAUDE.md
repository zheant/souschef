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

## Pilote — confirmation du garde-manger en deux temps (2026-08-11)

**Retirée depuis** (section « Implémentation mobile du reste de l'app »
plus bas dans ce fichier) : ce mécanisme faisait double emploi avec
« à acheter » dans la sous-catégorie garde-manger de la liste d'épicerie
(tranche « Écran Résultat — refonte réelle ») — un mécanisme réactif
(corriger après coup, une fois le menu déjà connu) a remplacé le
mécanisme proactif décrit ci-dessous (déclarer avant même de voir le
menu). Laissé ici tel quel comme trace de l'état au moment de cette
session historique, même convention que D15/D18 plus haut.

Deuxième tranche du pilote produit, construite sur la tranche précédente :
génère d'abord un menu, propose une liste courte et priorisée d'ingrédients
(`GET /api/plan/{id}/pantry_prompt`), laisse l'utilisateur répondre
« aucun/un peu/assez » (quantité exacte facultative), puis réoptimise en
tenant compte du stock déclaré et explique ce qui a changé — en réutilisant
telle quelle la mécanique `reoptimize_plan`/`MenuChange` de la tranche
précédente (aucun verrou/exclusion, juste `enable_pantry_stock=True`).

`services/planning.py::pantry_prompt` n'invente aucun nouveau calcul : il
assemble `Plan.ingredient_needs` (déjà stocké à la génération) avec
`services/validation.py::min_taxed_price_per_base_unit` (déjà utilisé pour
l'assertion 1) pour estimer un coût par ingrédient, et priorise par deux
critères explicites additionnés (pas un score pondéré arbitraire) : top 5
par coût estimé, top 3 par périssabilité ≥ 0,5 non déjà inclus.

**Mapping assez/un peu → quantité, décision à retenir** : « assez » =
besoin exact du plan actuel pour cet ingrédient, « un peu » = la moitié —
jamais une valeur arbitrairement gonflée, qui fausserait la comptabilité de
`_apply_commit` au commit suivant (le stock resterait « miraculeusement »
élevé au lieu de se consommer réellement semaine après semaine).

Portée volontairement restreinte, comme D15 le documentait déjà pour un cas
voisin : pas de critère « requis en grande quantité » séparé (n'a pas de
base objective pour normaliser g/ml/unité sans données réelles — capturé
indirectement par le classement en coût) ; pas de niveau « doit être
utilisé » (contrainte dure) sur les périssables — c'est la tranche
« Périssables prioritaires ou obligatoires », explicitement écartée par
l'utilisateur au profit de celle-ci.

Front-end : `Generate.tsx` passe de un à trois écrans internes (`form` →
`confirm-pantry` → `confirmed`) sans nouvel onglet ni routeur — juste un
état local à trois phases, cohérent avec le modèle de navigation par
onglets déjà en place. `describeChanges` (l'explication de réoptimisation)
a été extrait de `Result.tsx` vers `frontend/src/changes.ts`, partagé entre
les deux écrans plutôt que dupliqué.

**Vérifié contre PostgreSQL réel** : **96/96 tests passés, 0 sauté** (93
avant ce chantier + 3 nouveaux, dont un test bout en bout qui déclare
« assez » de riz puis réoptimise et vérifie que le poste achats **baisse
strictement** — pas seulement que les endpoints répondent). `tsc -b`/
`vite build` propres. **Mise à jour** : l'utilisateur a testé cette tranche
et la précédente (verrouillage/remplacement) manuellement via
`docker compose up` et confirmé « le tout fonctionne » — les deux sont
maintenant vérifiées en navigateur, pas seulement par la suite de tests.

## Pilote — périssables prioritaires ou obligatoires (2026-08-11)

**Retirée depuis** (section « Pilote — garde-manger retiré, remplacé par
les essentiels » plus bas dans ce fichier) : le garde-manger à quantité
suivie entier a été retiré, `must_use`/`use_soon` avec lui — `use_soon`
était déjà inerte sur le solveur (noté ci-dessous) et `must_use` n'a pas
d'équivalent dans les essentiels (pure appartenance, sans notion de
contrainte dure de consommation minimale). Laissée ici telle quelle comme
trace de l'état au moment de cette session historique, même convention que
D15/D18.

Quatrième tranche du pilote produit, complément de la confirmation du
garde-manger : `household.pantry_stock` gagne `priority`
(`normal`/`use_soon`/`must_use`, migration `c3d8f21a9e6b`). Seul
`must_use` a un effet sur le solveur — `use_soon` est stocké (schéma, API,
sélecteur dans l'écran Garde-manger) mais **sans effet sur le solveur en
v1** : une vraie préférence douce demanderait un sixième terme d'objectif,
alors que l'objectif actuel a exactement cinq termes nommés
(`ObjectiveTerms`), documentés et testés en profondeur (décomposition en
cinq barres, rapport de diagnostic) — un chantier à part entière, pas un
ajout mineur greffé ici.

`must_use` : `SolverConfig.must_use_pantry_ids` (même famille « dérivé,
jamais fourni à la main » que `locked_recipe_servings`), nouvelle
contrainte `solver/model.py::_add_must_use_pantry` —
`demand_expr(i) ≥ 0,5·g_i` (réutilise `demand_expr`, déjà là pour la
couverture ; fraction fixe à 0,5, pas configurable — « ne signifie pas
automatiquement que toute la quantité doit être consommée »). Sans effet si
`enable_pantry_stock` est inactif (g_i n'est même pas dans le modèle).
`services/planning.py::_with_must_use_pantry` la dérive depuis
`pantry_stock.priority` et lève `PantryIngredientNotUsableError`
**avant** le solveur si l'ingrédient n'apparaît dans aucune recette du
catalogue — jamais un statut `Infeasible` muet, même principe que
`RecipeNotLockableError`.

**Piège identifié et évité en conception** : `PUT /api/pantry` (quantité)
est appelé par deux flux distincts — l'écran Garde-manger manuel et la
confirmation en deux temps de la tranche précédente, qui n'envoie jamais de
priorité. `priority` vit donc sur un endpoint **strictement séparé**
(`PUT /api/pantry/{id}/priority`, `services/household.py::
set_pantry_priority`) — sinon chaque confirmation de garde-manger aurait
silencieusement écrasé un « doit être utilisé » déjà posé. Vérifié par un
test de régression dédié (`test_update_pantry_never_resets_priority`).

**Vérifié contre PostgreSQL réel** : cycle de migration
`downgrade base` → `upgrade head` propre ; **103/103 tests passés, 0
sauté** (96 avant ce chantier + 7 nouveaux — un test solveur qui construit
un scénario discriminant où la contrainte *change* réellement la sélection
(dahl_toy 2→3 portions, pas seulement trivialement satisfaite), le test de
régression anti-écrasement, et la validation `PantryIngredientNotUsableError`
sur un ingrédient synthétique qu'aucune recette ne référence). `tsc -b`/
`vite build` propres. **Mise à jour** : l'utilisateur a testé cette tranche
dans un navigateur et confirmé qu'elle fonctionne ; il a aussi relevé au
passage que la liste d'épicerie n'affichait que la marque du produit, pas
le type d'ingrédient (« Great Value, 900 g » sans dire que c'est du riz) —
corrigé dans la foulée (`services/planning.py::_grocery_list` joint
maintenant `CanonicalIngredient.name`, champ `ingredient_name` ajouté à
`GroceryLine`, verrouillé par un test).

## Pilote — questionnaire initial et résumé en langage naturel (2026-08-11)

Cinquième tranche, purement front-end (aucun changement backend, aucune
migration) : `screens/Household.tsx` cache désormais ρ_h derrière trois
préréglages (« Petit/Moyen/Grand appétit », valeurs 0,6/1,0/1,4, choisies
pour rester cohérentes avec le profil de seed `ρ = (1,0 ; 1,0 ; 0,6)`,
D9) — un member existant dont la valeur ne correspond à aucun préréglage
affiche « Autre (x,xx) » sans la modifier silencieusement. Un résumé en
langage naturel («N personnes, N repas à prévoir, cuisine rapide...») se
recalcule en direct depuis l'état du formulaire, à côté de `D` (inchangé).

κ/ε/K/R_min/α/latitude/longitude **restent des champs numériques exacts**
(aucune retraduction en catégories) mais repliés sous un `<details>`
« Paramètres avancés » — cohérent avec « les préférences non essentielles
peuvent être ignorées et complétées plus tard », rien n'est supprimé ni
perdu. **Hors périmètre, volontairement** : le check-in hebdomadaire
(sorties/invités — aucun champ du modèle ne les représente aujourd'hui,
toucherait le calcul de la demande D9, pas seulement l'écran) et les
magasins accessibles/programmes de fidélité (aucune notion de magasins
accessibles au ménage dans le modèle ; les prix membres sont une extension
de la résolution de prix D15/D18, un chantier à part — `docs/product-pilot.md`
classe lui-même les offres ciblées « hors du premier périmètre »).

**Vérifié** : `tsc -b`/`vite build` propres. Aucun test backend affecté
(aucun fichier backend modifié — confirmé par `git status`). Testé par
l'utilisateur dans un navigateur — fonctionne.

## Pilote — liste d'épicerie à cocher (2026-08-11)

Sixième tranche, purement front-end (`Result.tsx`, plus une poignée de
classes CSS minimales) : deux vues bascule-ables sur la liste d'épicerie —
« Liste à cocher » (par défaut, sans prix, une ligne `{ingredient_name} —
{units} × {package_unit}` par produit, cochée = barrée) et « Vue
détaillée » (la table existante, inchangée). État `checked` local,
réinitialisé à chaque nouveau plan (même motif que `lockedIds`).

**Hors périmètre, volontairement** :
- **Pas de regroupement par catégorie** — aucun champ catégorie
  n'existe sur `canonical_ingredient`/`product` ; regroupement par magasin
  seulement, comme la vue détaillée. Une vraie catégorisation est un
  chantier de données (curation), pas d'affichage.
- **Pas de rabais/économies dans la vue détaillée** — le pipeline actuel
  (`PurchaseLine` → `_grocery_list`) ne transporte que le prix payé, ni
  `is_promo` ni le prix régulier de `market.price`, alors que ces deux
  champs existent en base mais ne sont jamais chargés dans
  `ProblemData.prices` (`PriceData` n'a que `price_cents_cad`/`is_promo`,
  pas le prix régulier). Les faire transiter de bout en bout est un
  chantier séparé (5-6 fichiers back-end), pas un ajout mineur. `.badge.promo`
  existe déjà dans `styles.css`, jamais utilisé — ce manque était déjà
  pressenti avant cette session.
- **Pas de persistance de l'état coché** — aucun concept « coché/acheté »
  côté serveur ; le flux « liste précochée après achat, correction des
  absences/substitutions avant mise à jour du stock » (`docs/product-pilot.md`)
  est une fonctionnalité à part entière adossée au `commit` existant, pas
  une case à cocher isolée.

**Vérifié** : `tsc -b`/`vite build` propres, aucun fichier backend modifié
(confirmé par `git status`). Testé par l'utilisateur dans un navigateur —
fonctionne.

## Pilote — rabais et économies dans la liste d'épicerie (2026-08-11)

Septième tranche, suivi direct de la précédente : `market.price` porte déjà
`is_promo`/`regular_price_cents_cad` en base, mais aucune couche ne les
faisait transiter jusqu'à la ligne d'épicerie — vérifié en lisant le code,
pas supposé (`solver/model.py::_Ctx` construisait déjà `price_is_promo`
depuis `problem.prices`, jamais relu ailleurs ; `.badge.promo` existait déjà
dans `styles.css`, jamais référencé). Le champ manquant suit maintenant
exactement le chemin déjà emprunté par le prix payé, un maillon de plus à
chaque étape : `services/problem_data.py::PriceData` (nouveau champ) →
`solver/model.py::_Ctx` (`self.regular_price_cents`, même boucle que
`price_cents`/`price_is_promo`) → `solver/port.py::PurchaseLine` (deux
nouveaux champs, avec défauts pour ne pas casser
`tests/test_substitutability.py::FakeSolver`) →
`services/planning.py::_persist_plan` (sérialisation JSONB) →
`_grocery_list` (calcul de `savings_cents_cad`, taxé comme
`taxed_total_cents_cad`, `None` sauf promo réelle avec prix régulier
supérieur — jamais une valeur inventée).

**Hors périmètre, volontairement** : seule la référence « prix régulier du
même produit » est construite. La seconde référence honnête demandée par
`docs/product-pilot.md` — « achat du même panier dans le magasin habituel »
— exige de résoudre le même panier à un magasin de référence différent, un
calcul à part, pas une lecture. Aucun sixième terme d'objectif non plus :
les économies affichées sont une lecture du diagnostic déjà résolu, pas un
facteur qui influence le choix du solveur (même limite déjà posée pour
`use_soon`).

**Vérifié contre PostgreSQL réel** : **105/105 tests passés, 0 sauté** (103
avant ce chantier + 2 nouveaux — un test qui confirme l'absence d'effet sur
le seed jouet, sans promo par construction, et un test discriminant qui
mute directement une ligne `market.price` déjà chargée (pas d'insertion en
conflit) pour vérifier le calcul taxé des économies). Correction en cours
de route : deux sites de construction de `PriceData` en dehors de
`load_problem_data` (`tests/seed_loader.py`, `tests/conftest.py::
make_problem`) ignoraient déjà `regular_price_cents_cad` — le nouveau champ
obligatoire les a fait échouer immédiatement, corrigés. `tsc -b`/
`vite build` propres. Aucune migration (la donnée existait déjà en base,
seule la lecture était incomplète). Testé par l'utilisateur dans un
navigateur (avec `seed/main` — le seed jouet n'a aucune promo par
construction) — fonctionne.

## Pilote — passe responsive (2026-08-11)

Huitième tranche, purement CSS + un conteneur de défilement ajouté autour
de chaque table (`Household.tsx`, `Pantry.tsx`, `Generate.tsx`,
`Result.tsx` ×2, `Diagnostic.tsx`) — aucune restructuration de colonnes,
aucun changement backend. Décidé explicitement avec l'utilisateur de
séparer cette tranche d'une éventuelle refonte graphique (palette/
typographie) : l'appli a déjà un thème délibéré (« grocery flyer »), pas un
défaut non stylé.

`frontend/index.html` avait déjà la balise viewport correcte (vérifié, pas
un oubli fondamental) ; le vrai trou était l'absence de gestion de
débordement sur les tables `.ledger`, plus `header.masthead` sans
`flex-wrap` (titre + sous-titre pouvaient déborder sous ~375px). Nouvelle
classe `.table-scroll` (`overflow-x: auto`), et une règle globale
`input[type="checkbox"], input[type="radio"] { width: 18px; height: 18px;
... }` qui remplace les surcharges locales dispersées
(`.checklist`/`.flags` avaient chacune leur propre `width: auto` —
supprimées, redondantes avec la règle globale).

**Hors périmètre, volontairement, au premier passage** : pas de
transformation des tables en cartes empilées sur mobile (jugée une vraie
décision de design, pas une correction) ; pas de nouvelle navigation
mobile (le défilement horizontal de `nav.tabs`, déjà présent à 640px,
suffit — ça, ça tient toujours).

**Correction après test réel par l'utilisateur** : le défilement
horizontal seul restait pénible sur les tables à 4-6 colonnes (menu,
épicerie détaillée) — sans contrainte de largeur, la table s'étire
librement à son contenu non replié, donc `.table-scroll` fait exactement
ce qu'il promet (contenir le débordement dans la carte) mais ne réduit
jamais la largeur réelle à parcourir. Ce que j'avais mis « hors périmètre,
volontairement » s'est donc avéré nécessaire dès le premier test — pas une
extension de portée, une correction de ce qui avait été livré comme
suffisant. Ajouté sous `@media (max-width: 640px)` : chaque `table.ledger`
passe en empilement vertical (`display: block` sur `tr`/`td`, `thead`
caché), un `data-label` posé sur les `<td>` des tables à en-tête
(`Household.tsx`, `Pantry.tsx`, les deux tables de `Result.tsx`) restitue
l'en-tête de colonne via `content: attr(data-label)`. La table
`Diagnostic.tsx` n'a pas d'en-tête (déjà `libellé | valeur` en colonne 1)
— pas besoin de `data-label`, l'empilement seul suffit à faire replier la
valeur au lieu de forcer la largeur.

**Deuxième correction, même test** : la table de confirmation du
garde-manger (`Generate.tsx`) a trois colonnes radio « Aucun/Un peu/
Assez » dont le libellé n'existait qu'au niveau du `<thead>` — invisible
une fois `thead` caché en empilement mobile, et je n'avais pas pensé à y
poser `data-label` (cette table n'avait pas été touchée par la passe
`.table-scroll` initiale car elle n'a qu'une seule variante). Corrigé en
mettant le libellé directement dans un `<label>` visible à côté de chaque
bouton radio (`{optLabel}` après l'`<input>`), plutôt que via
`data-label`/`::before` comme les autres tables — plus robuste ici
(fonctionne identiquement en desktop et mobile, agrandit aussi la cible
cliquable) et cohérent avec le principe qu'un contrôle de formulaire doit
toujours avoir son libellé visible à côté de lui, pas seulement dans un
en-tête de colonne qui peut disparaître.

**Vérifié** : `tsc -b`/`vite build` propres, aucun fichier backend modifié
(confirmé par `git status`). Les deux correctifs répondent à un test réel
de l'utilisateur en navigateur mobile — pas encore re-testés par lui après
ce second correctif.

## Écran Résultat — refonte réelle, piste « circulaire du quartier » (2026-08-11)

**Sous-thread garde-manger/« à acheter »/Replanifier retiré depuis**
(section « Pilote — garde-manger retiré, remplacé par les essentiels » plus
bas dans ce fichier) : le garde-manger à quantité suivie entier — dont tout
ce sous-thème est solidaire — a été retiré. Le reste de cette tranche
(disposition, glissement, détail recette, `GET /api/recipes/{id}/
ingredients`) reste d'actualité. Laissé ici tel quel comme trace de l'état
au moment de cette session historique, même convention que D15/D18.

Neuvième tranche du pilote : implémentation en production de la
disposition « P » convergée après six rounds de maquettes interactives
(atelier visuel, artefacts séparés, non versionnés). `Result.tsx` est
réécrit en profondeur — deux onglets internes (Cette semaine / Épicerie),
coût simplifié (achats épicerie + temps de cuisine seulement, la
décomposition en 5 termes devenant une vue optionnelle sans montant,
accessible en touchant la barre), cartes recette glissables (Garder/
Remplacer révélés au glissement, pas affichés par défaut), détail recette
en pleine page avec bouton retour explicite, garde-manger avec « à
acheter » résolu au moment d'accepter le plan, liste d'épicerie avec
prix/marque/badge rabais et cases à cocher désactivées avant acceptation.
Scopé à une nouvelle classe CSS `.result-v2` avec ses propres jetons de
couleur/typographie (piste A) — **aucun autre écran n'est touché**,
extension au reste de l'app volontairement hors périmètre (garde le
thème « registre d'épicerie » existant partout ailleurs pour l'instant).

**Décisions de conception à retenir** :
- **Le glissement révèle en faisant grandir un vrai panneau flex, jamais
  en translatant le contenu.** Un essai précédent (prototype) translatait
  la carte entière pour révéler les actions en dessous — ça coupait le
  début du nom de la recette dès que la largeur révélée dépassait
  l'espace occupé par la photo. `SwipeRow` (composant interne à
  `Result.tsx`) fait grandir `.rp-swipe-actions` (un vrai frère flex, pas
  une superposition) : la carte rétrécit, le nom (sur sa propre ligne,
  autorisé à se replier) reste toujours entièrement visible.
- **« À acheter » ne touche rien au moment du clic.** Marquer un
  ingrédient du garde-manger est un état local (React) jusqu'à
  « Accepter » — c'est `commit_plan(..., buy_instead_ids)` qui résout le
  magasin le moins cher et ajoute la ligne d'achat, une seule fois, au
  moment où l'acceptation devient réelle. `services/planning.py::
  _cheapest_purchase_for_ingredient` réutilise le critère de
  `validation.py::min_taxed_price_per_base_unit` (assertion 1) mais
  conserve l'identité du produit/magasin gagnant au lieu de la jeter.
  `_apply_commit` force `consommé=0` pour ces ingrédients quel que soit
  `enable_pantry_stock` — l'utilisateur dit explicitement ne pas avoir le
  stock, il ne doit jamais être décrémenté pour lui.
- **Remplacer appelle réellement `reoptimize_plan`**, pas une simulation
  locale : la liste d'épicerie et le garde-manger affichés sont dérivés du
  `plan` reçu en prop, jamais dupliqués en état local — un nouveau plan
  après remplacement les régénère donc automatiquement, sans code
  spécifique. `_grocery_list` le faisait déjà pour les achats ; le vrai
  ajout de cette tranche est `_plan_pantry_lines` (nouveau), qui résout
  enfin `diagnostic.pantry_consumed_by_ingredient` (id → quantité,
  existait depuis l'étape 5) en nom — jamais fait nulle part avant.
- **Bug trouvé et corrigé après coup (2026-08-11, question directe de
  l'utilisateur)** : la phrase ci-dessous affirmait « la comptabilité
  réelle est correcte » — elle ne l'était qu'à moitié. `_apply_commit`
  forçait bien `consommé=0` pour un ingrédient « à acheter » (le stock
  n'était pas décrémenté), mais le calcul du nouveau stock partait quand
  même de l'ancienne quantité déclarée (`qty = stock_déclaré + (acheté −
  besoin)`) — si le ménage avait déclaré à tort 500 g d'un ingrédient
  qu'il marque ensuite « à acheter », les 500 g fautifs survivaient tels
  quels après le commit, avec le reliquat du nouvel achat ajouté par-dessus.
  L'utilisateur a demandé explicitement : « il faudrait mettre la quantité
  à 0 ». Corrigé — `stock` est maintenant traité comme 0 (pas seulement
  `consommé`) pour ces ingrédients dans `_apply_commit` ; le nouveau
  stock devient `0 + (acheté − besoin)`, c'est-à-dire uniquement le
  reliquat du paquet réellement acheté cette fois, jamais l'ancienne
  valeur fausse. Test `test_commit_with_buy_instead_picks_cheapest_product_and_spares_stock`
  renforcé avec une valeur de stock initial délibérément fausse et
  distinctive (500 g) pour prouver qu'elle est écartée, pas seulement
  « non décrémentée » — **109/109 tests passés** après correction.
- **Limite restante, assumée** : après un commit avec `buy_instead_ids`,
  le `diagnostic` persisté (donc `pantry_lines` à la relecture) n'est
  **pas** recalculé — il reste un instantané de la résolution d'origine,
  qui listera encore l'ingrédient comme « consommé du garde-manger » même
  s'il vient d'être basculé vers un achat réel. Seul l'affichage du
  garde-manger, si on rouvre l'onglet Épicerie après coup, peut sembler
  périmé — la comptabilité réelle de `pantry_stock`, elle, est maintenant
  correcte (voir ci-dessus). Corriger l'affichage demanderait de
  régénérer le diagnostic au commit, hors périmètre.
- **Deuxième bug trouvé et corrigé (2026-08-11, test réel de
  l'utilisateur — « pourquoi acheter 2×1 L de bouillon ? »)** : la
  quantité résolue pour un ingrédient « à acheter » était
  `plan.ingredient_needs[iid]`, le **besoin total** du plan pour cet
  ingrédient — pas ce qui manquait réellement. Si le plan achetait déjà
  une partie de l'ingrédient normalement (le complément au-delà de ce que
  le garde-manger était censé couvrir), « à acheter » rachetait le besoin
  entier par-dessus, doublant l'achat. Corrigé : nouvelle fonction
  `_purchased_by_ingredient` calcule ce qui est déjà dans
  `plan.purchases` **avant** d'ajouter les lignes de remplacement ;
  seul le manque (`besoin_total − déjà_acheté`, jamais négatif) est
  acheté en plus, arrondi en paquets entiers du produit le moins cher.
  Nouveau test discriminant
  `test_commit_buy_instead_does_not_rebuy_what_is_already_in_the_grocery_list`
  (400 g déjà achetés, besoin 500 g → seulement 100 g de plus, pas 500 g
  par-dessus). Le contrôle de validité de `buy_instead_ids` change aussi
  de base : il vérifie maintenant l'appartenance à
  `diagnostic.pantry_consumed_by_ingredient` (ce qui apparaît réellement
  dans « Garde-manger — à récupérer ») plutôt qu'à `ingredient_needs`
  (tout ingrédient du plan, y compris ceux jamais destinés à venir du
  garde-manger) — plus fidèle à ce que l'écran propose réellement de
  marquer.
- **Troisième correctif, demandé dans la même session** : une fois un
  plan accepté, ses recettes ne peuvent plus être remplacées —
  `reoptimize_plan` lève `PlanAlreadyCommittedError` (409) si
  `previous.status == PlanStatus.committed`, avant même de toucher le
  solveur. Sans ce garde-fou, remplacer une recette après acceptation
  produirait un nouveau plan dont le menu ne correspond plus à ce que la
  comptabilité de `pantry_stock`/achats a déjà enregistré comme
  définitif — désynchronisation silencieuse entre le stock réel et le
  menu affiché. Boutons Garder/Remplacer désactivés côté front-end
  (`Result.tsx`, `disabled={reoptimizing || accepted}`) avec une note
  explicative (« Menu verrouillé — plan déjà accepté ») — le 409 côté
  serveur reste la garantie réelle, le front-end n'est qu'une prévention
  d'UX.
- **Vérifié contre PostgreSQL réel après ces trois correctifs** :
  **112/112 tests passés, 0 sauté** (109 avant cette session + 3
  nouveaux). `tsc -b`/`vite build` propres.

**Pivot architectural (même session, après un nouveau test réel — « ça ne
fonctionne toujours pas, des ingrédients restent dans la liste
d'épicerie »)** : le mécanisme de correction du garde-manger « à
acheter » au moment du commit (les deux correctifs ci-dessus) est
**retiré entièrement**, pas re-corrigé une troisième fois. Décision de
l'utilisateur, après avoir vu la deuxième panne : résoudre un achat de
remplacement après coup, avec une heuristique séparée
(`_cheapest_purchase_for_ingredient`), s'est avéré structurellement
fragile — deux bugs réels trouvés en test manuel en une seule session,
chacun corrigé en ajoutant une couche de calcul supplémentaire par-dessus
la précédente. Plutôt que d'empiler un troisième correctif, la
correction se fait maintenant **avant** la résolution, avec le vrai
solveur :

- Marquer un ingrédient « à acheter » reste un état local (React,
  `buyInsteadIds`) — inchangé.
- Un nouveau bouton **« Replanifier »** (visible dès qu'au moins un
  ingrédient est marqué, tant que le plan n'est pas accepté) apparaît
  avec une case à cocher **« Fixer les recettes de la semaine »**
  (cochée par défaut — même défaut que « Remplacer » : ne pas changer le
  menu sans qu'on le demande explicitement).
- Au clic : `PUT /api/pantry` met réellement `pantry_stock` à 0 pour
  le(s) ingrédient(s) marqué(s) (persisté immédiatement, pas différé au
  commit), puis `POST /api/plan/{id}/reoptimize` est appelé avec
  `enable_pantry_stock: true` et, si la case est cochée,
  `locked_recipe_ids` = toutes les recettes du plan courant (sinon
  liste vide — réoptimisation libre). C'est le solveur, pas une
  heuristique séparée, qui décide alors du panier réellement optimal —
  le même mécanisme déjà éprouvé pour « Remplacer ».
- **Retiré du backend** : `_cheapest_purchase_for_ingredient`,
  `NoProductForIngredientError`, `UnknownBuyInsteadIngredientError`, le
  paramètre `buy_instead_ids` de `commit_plan`/`_apply_commit`,
  `CommitRequest` (schéma). `commit_plan`/`POST /api/plan/{id}/commit`
  redeviennent sans paramètre, comme avant l'introduction de « à
  acheter ». `_purchased_by_ingredient` (le calcul factoré de la
  quantité déjà achetée par ingrédient) est **conservé** — c'est un
  nettoyage de `_apply_commit` indépendant du mécanisme retiré. Les 3
  tests spécifiques à l'ancien mécanisme sont supprimés (pas laissés en
  l'état) ; le test de `pantry_lines` (toujours valide, sans rapport
  avec le retrait) est conservé séparément.
- `PlanAlreadyCommittedError`/le verrouillage du menu après acceptation
  (troisième correctif ci-dessus) **reste inchangé** — toujours
  nécessaire, `Replanifier` appelle le même `reoptimize_plan` désormais
  gardé.
- **Vérifié contre PostgreSQL réel** : **109/109 tests passés, 0
  sauté** (112 − 3 retirés avec le mécanisme, aucun nouveau test —
  tranche de retrait/redirection vers un mécanisme déjà testé, pas de
  nouvelle logique métier côté solveur). `tsc -b`/`vite build` propres.
  **Non vérifié** : interaction réelle en navigateur — aucun affichage
  disponible dans cette session.
- **Photos de recette : dégradés de couleur dérivés de l'id**, pas de
  vraies photos — aucune source d'images n'existe dans le modèle de
  données. Chantier de données séparé, pas une question de disposition
  (répété depuis le round 4 des maquettes).
- Nouvelle route `GET /api/recipes/{id}/ingredients`
  (`services/catalog.py::get_recipe_ingredients`) : `Recipe.ingredients`
  existait en base depuis l'étape 1 mais n'était exposé par aucune route —
  nécessaire pour que le détail recette en plein écran affiche de vrais
  ingrédients.

**Vérifié contre PostgreSQL réel** : **112/112 tests passés, 0 sauté**
(105 avant ce chantier + 7 nouveaux — le choix du magasin/produit le
moins cher testé sur un cas discriminant du seed jouet où riz a deux
produits à des prix par unité différents, le fait que le stock n'est
jamais décrémenté pour un ingrédient « à acheter », le rejet explicite
d'un id absent des besoins du plan, `pantry_lines` résolu en nom, et les
deux endpoints via le contrat HTTP). `tsc -b`/`vite build` propres. Un
lissage de bord trouvé et corrigé en cours de route : le premier jet de
`SwipeRow` exposait sa fonction `close()` via une propriété statique
partagée sur le composant plutôt qu'un callback par instance — chaque
carte aurait fermé la dernière carte rendue au lieu d'elle-même ; corrigé
en passant `actions` comme fonction `(close) => ReactNode` plutôt que du
JSX brut. Sondé en direct contre la pile de développement de
l'utilisateur (`docker compose up`, pas seulement la base de test) :
`GET /api/recipes/{id}/ingredients` et `pantry_lines` sur `POST
/api/plan` répondent correctement contre `seed/main` (données réelles,
pas le jouet) — un plan de test a été créé dans cette base au passage
(id 237, non commis, aucune mutation de `pantry_stock`). **Non vérifié** :
interaction réelle dans un navigateur — aucun affichage disponible dans
cette session, à faire manuellement avant de considérer cette tranche
terminée, en particulier le glissement tactile réel (testé ici seulement
par la logique des événements pointeur, jamais au doigt), la bascule de
la barre, le détail recette plein écran, et l'enchaînement marquer « à
acheter » → Accepter → recharger le plan.

## Implémentation mobile du reste de l'app — 3 onglets, piste A partout (2026-08-11)

Dixième tranche : la structure de navigation à 5 onglets devient 3
onglets (**Planification** / **Ménage** / **Paramètres**), et la piste
visuelle A (papier chamois, encre brique, `Result.tsx`) devient le thème
global de toute l'app plutôt que scopée à un seul écran — décision
explicite de l'utilisateur (« étendre piste A partout maintenant »
plutôt que « structure seulement »).

- **Planification** (`screens/Planning.tsx`, nouveau, remplace
  `Generate.tsx`) : orchestrateur mince entre la génération et le
  résultat — bouton Générer seul au départ, puis rend `Result.tsx`
  directement une fois un plan obtenu (ses sous-onglets « Cette semaine »/
  « Épicerie » existaient déjà, exactement ce qui était demandé). Piège
  identifié et évité : Génération et Résultat étaient deux onglets
  distincts, donc toujours accessibles séparément ; fusionnés en un seul
  écran qui affiche automatiquement le résultat dès qu'un plan existe,
  il n'y avait plus moyen de revenir au formulaire pour un nouveau plan —
  ajouté un bouton « ‹ Générer un nouveau plan » qui force l'affichage du
  formulaire même quand `plan` est déjà présent.
- **Confirmation du garde-manger en deux temps retirée** (décision de
  l'utilisateur, pas une simplification silencieuse) : faisait double
  emploi avec « à acheter » de la tranche précédente. Retrait complet,
  pas un contournement — `services/planning.py::pantry_prompt`,
  `PantryPromptLine`, les constantes `PANTRY_PROMPT_*`, la route `GET
  /api/plan/{id}/pantry_prompt`, `PantryPromptLineOut`, et leurs
  équivalents front-end (`api.pantryPrompt`, type `PantryPromptLine`)
  sont supprimés, pas laissés en code mort. Le mécanisme sous-jacent
  (stock déclaré + `enable_pantry_stock` réduisant les achats) reste
  couvert par `test_commit_decrements_and_reports_to_pantry` et
  `test_generate_plan_respects_must_use_pantry` — `reoptimize_plan` et
  `generate_plan` partagent le même appel solveur/persistance, retirer le
  test qui passait spécifiquement par `reoptimize` ne perd donc pas de
  couverture réelle sur le mécanisme lui-même. `docs/product-pilot.md`
  (le brief produit d'origine) **n'est pas modifié** — la divergence est
  documentée ici, jamais dans le document source (même règle que pour
  `docs/spec.md`, appliquée par analogie).
- **Ménage** (`screens/Household.tsx`, réécrit) : trois sous-sections
  (Garde-manger/Membres/Préférences) via un nouveau composant global
  `.subnav`, réutilisable (généralisé depuis `.rp-segmented` de
  `Result.tsx`). Les paramètres avancés (κ/ε/K/R_min/α/latitude/
  longitude) rejoignent Préférences plutôt que Paramètres — décision
  explicite de l'utilisateur : ce sont des réglages du ménage, pas des
  outils de développement, même si ce sont des champs numériques exacts.
  `screens/Pantry.tsx` exporte maintenant `PantryPanel` (sous-composant,
  plus d'écran de haut niveau à lui seul) — logique interne inchangée,
  garde son propre bouton Enregistrer (appel API distinct de celui de
  Membres/Préférences, qui partagent un seul `api.updateHousehold` via
  une nouvelle barre d'action collante globale `.sticky-bar`).
- **Paramètres** (`screens/Diagnostic.tsx`) : renommage du titre
  seulement (« Diagnostic » → « Paramètres »), aucun changement de
  logique — « pour l'instant, les fonctions développement » (mot de
  l'utilisateur), un vrai écran de réglages utilisateur reste un chantier
  séparé, non commencé.
- **Thème global** (`styles.css`) : les *valeurs* des jetons `:root`
  changent (pas les noms — `--leek` reste `--leek` mais devient la
  brique de la piste A, `--cranberry` devient un bordeaux plus sombre
  pour rester visuellement distinct comme couleur de danger), `body`
  passe en Georgia, `--mono` en Courier New, et `h2`/`.masthead h1`/
  `nav.tabs button`/`button.action` gagnent le traitement « display »
  (Arial condensé gras) déjà défini pour `.rp-disp` dans `Result.tsx` —
  copié, pas réinventé. `.result-v2` et ses jetons `--rp-*` locaux ne
  sont **pas** retirés : redondants avec `:root` maintenant, mais les
  toucher pour « nettoyer » aurait été un risque de régression sur un
  écran déjà vérifié en navigateur pour un gain cosmétique nul.

**Hors périmètre, volontairement** : reconstruire les tables Membres/
Garde-manger en cartes glissables façon `Result.tsx` — glisser une
recette a un sens produit (Garder/Remplacer) que glisser une ligne de
garde-manger n'a pas eu de demande explicite ; `.table-scroll` +
empilement mobile (passe responsive) reste le traitement de ces tables.

**Vérifié contre PostgreSQL réel** : **109/109 tests passés, 0 sauté**
(112 avant ce chantier − 3 retirés avec `pantry_prompt`, aucun nouveau
test ajouté — tranche de retrait/réorganisation, pas de nouvelle
logique métier). `tsc -b`/`vite build` propres. `git status` confirme
que seuls les fichiers listés ci-dessus ont changé côté backend.
**Sondage en direct contre la pile de développement de l'utilisateur
incomplet cette fois** : `GET /api/plan/{id}/pantry_prompt` répond
encore 200 sur leur conteneur en cours d'exécution (openapi.json
confirmé) — le processus `uvicorn --reload` de leur pile n'a
apparemment pas rechargé ce changement précis, contrairement au sondage
réussi de la tranche précédente. Un redémarrage (`docker compose up
--build`) est nécessaire avant le test manuel. **Non vérifié** :
interaction réelle dans un navigateur — aucun affichage disponible dans
cette session. À faire manuellement après redémarrage : les 3 onglets,
Planification (bouton → résultat direct, sans étape de confirmation
garde-manger, et le nouveau bouton « Générer un nouveau plan » depuis un
résultat déjà affiché), Ménage (bascule entre les 3 sous-sections,
sauvegarde Membres/Préférences, garde-manger inchangé), Paramètres
(drapeaux/rapport inchangés), et que le nouveau thème s'affiche
correctement partout.

## Nettoyage — code mort (2026-08-11)

Audit demandé explicitement par l'utilisateur (« parcourir l'entièreté du
codebase et retirer toutes les fonctions inutiles »), rapport présenté et
approuvé avant toute suppression. Conclusion principale : **le backend
n'a aucune fonction morte** (156 définitions passées en revue, grep de
chaque nom dans tout le dépôt — tout ce qui semblait sans appelant est en
fait une route FastAPI, un validateur Pydantic, ou une implémentation
injectée délibérément substituable) et **le frontend non plus**
(`tsc --noUnusedLocals --noUnusedParameters` ne relève rien). Le seul
gisement réel était du **CSS mort** — des styles jamais nettoyés après
que les écrans qui les utilisaient aient été remplacés :

- `.decomp` et ses 9 sous-règles + son override en media query — l'ancienne
  barre de décomposition en 5 termes, remplacée par `.rp-bigbar`/
  `.rp-splitbar` lors de la refonte mobile de l'écran Résultat.
- `.checklist` (3 règles) — l'ancienne vue « liste à cocher », remplacée
  par `.rp-item`.
- `.badge.promo` — remplacée par `.rp-promo-badge`.
- `button.danger` — jamais câblée à un bouton nulle part (aucune action
  destructive n'existe dans l'app).
- `.rp-disp`/`.rp-mono` — utilitaires créés pendant la refonte piste A,
  jamais appliqués via `className`.

Retirées (~17 règles). Vérifié par script (chaque classe CSS vs. chaque
`className` du code, aucune classe orpheline restante) puis par
`tsc -b`/`vite build` propres — bundle CSS 14,85 kB → 13,61 kB.

Cinq fonctions longues (`reoptimize_plan`, `_grocery_list`,
`_apply_commit`, `_build_result`, `_objective_terms`) ont été identifiées
comme candidates à la simplification puis **délibérément écartées** :
leur longueur reflète la complexité réelle du domaine (comptabilité
garde-manger, décomposition en 5 termes, résolution multi-magasin) et
plusieurs touchent directement la section « INVARIANTS — ne jamais
simplifier » plus haut dans ce fichier — aucune simplification proposée
sans la confiance qu'elle préserve la correction.

En cours de route : une affirmation périmée dans « Évaluation franche »
(un `print()` de debug jamais retiré de `demand.py`) s'est révélée
inexacte — corrigée (voir plus haut), avec sa mention dans « Leçon de
méthode » annotée en conséquence plutôt que réécrite.

## Pilote — garde-manger retiré, remplacé par les essentiels (staples) (2026-08-12)

Onzième tranche du pilote produit, pivot majeur demandé explicitement par
l'utilisateur après avoir creusé le terme 4 de l'objectif (récupération) :
`perishability` s'est révélé chargé mais jamais lu nulle part dans le
solveur (aucun mécanisme de péremption/décroissance n'existe). Plutôt que
d'ajouter un sixième terme d'objectif pour pousser à l'utilisation des
périssables, décision de l'utilisateur : retirer entièrement le
garde-manger à quantité suivie — ses corrections successives (« à
acheter », Replanifier, périssables prioritaires/obligatoires, documentées
plus haut dans ce fichier) reposaient toutes sur un input utilisateur
(quantités déclarées) qui diverge inévitablement du stock réel. Remplacé
par les **essentiels (staples)** : une simple appartenance
ménage/ingrédient, sans quantité ni priorité — un ingrédient que le ménage
est supposé toujours avoir sous la main.

**Mécanique** :
- `household.staple` (migration `f4b1a9d0c2e6`, remplace `pantry_stock` +
  l'enum `pantry_priority`) — `(household_profile_id,
  canonical_ingredient_id)`, aucune colonne de quantité.
- Un essentiel n'est jamais gratuit : `SolverConfig.enable_staples`
  (remplace `enable_pantry_stock`) ne change QUE l'objectif —
  `solver/model.py::_purchases_expr_cents` évalue un produit dont
  l'ingrédient est un essentiel au `min(prix courant, prix historique le
  plus bas de la dernière année)` (`services/pricing.py::
  historical_min_price_per_base_unit`, nouvelle fonction — fenêtre 365
  jours sur `Price.valid_from`, `market.price` conserve déjà tout
  l'historique, rien à stocker en plus). La couverture/le besoin ne
  bougent JAMAIS — `enable_staples` n'est donc plus dans
  `FLAGS_ALTERING_NEEDS`, contrairement à l'ancien `enable_pantry_stock` :
  propriété plus simple, documentée explicitement dans le code. Les
  montants réellement rapportés (`PurchaseLine.unit_price_cents_cad`,
  `_objective_terms`) continuent de lire les prix réels — jamais le prix
  biaisé de l'objectif.
- Après génération, `PlanView.needed_ingredients` (remplace
  `pantry_lines`) liste TOUS les ingrédients requis par le menu, avec
  `is_staple` — l'écran de confirmation (`Planning.tsx`, nouvelle phase
  entre générer et résultat) les présente en liste à cocher, essentiels
  pré-décochés (supposés déjà présents), le reste pré-coché (à acheter de
  toute façon). L'usager corrige ce qui manque réellement.
- `services/planning.py::finalize_plan` (nouveau, `POST
  /api/plan/{id}/finalize`) réutilise TEL QUEL `reoptimize_plan` — même
  mécanisme déjà éprouvé pour Remplacer/Replanifier, aucune résolution
  séparée — mais verrouille systématiquement TOUT le menu courant (jamais
  un choix de l'appelant, contrairement à Replanifier : finaliser ne
  change jamais les recettes) et pose `SolverConfig.
  confirmed_available_ids` (les ingrédients décochés) — `solver/model.py::
  _add_coverage` ne pose simplement pas la contrainte de couverture pour
  ces ingrédients ; aucune quantité de stock n'est jamais injectée nulle
  part (contrairement à l'ancien `pantry_stock`/`supply_expr`).

**Commit simplifié** : `commit_plan` redevient une simple validation +
passage à `PlanStatus.committed` — plus de comptabilité de stock à
décrémenter/reporter (`_apply_commit`/`_purchased_by_ingredient` retirés en
entier). `CommitResult.pantry_after_commit` disparaît de la réponse HTTP.

**Retiré en entier, backend** : `PantryStock`/`PantryPriority` (modèles),
`_add_must_use_pantry`/`MUST_USE_PANTRY_MIN_FRACTION`/
`_pantry_consumption` (solveur), `Diagnostic.
pantry_consumed_by_ingredient`/`pantry_consumed_value_cents`,
`services/household.py::get_pantry`/`update_pantry`/`set_pantry_priority`,
`services/planning.py::_with_must_use_pantry`/
`PantryIngredientNotUsableError`/`PlanPantryLine`/`_plan_pantry_lines`, les
routes `GET/PUT /api/pantry`, `PUT /api/pantry/{id}/priority`. Remplacés
par `services/household.py::get_staples`/`set_staples` (remplace tout
l'ensemble à chaque appel — pas un upsert ligne par ligne, plus simple :
un essentiel n'a ni quantité ni priorité à préserver), routes `GET/PUT
/api/staples`. Le seed (`seed/*/household.json`) passe de `"pantry": [...]`
(objets quantité) à `"staples": [...]` (liste d'ids).

**Retiré en entier, front-end** : `screens/Pantry.tsx`/`PantryPanel`
(remplacé par `screens/Staples.tsx`/`StaplesPanel` — liste simple
ajout/retrait), la section « Garde-manger — à récupérer » et tout le
mécanisme Replanifier (`buyInsteadIds`/`fixRecipes`/`replan()`) dans
`Result.tsx`, le partage Acheté/Garde-manger de la barre héro (un seul
montant désormais). `Household.tsx` : sous-onglet « Garde-manger » →
« Essentiels ». `Diagnostic.tsx` : `enable_pantry_stock` → `enable_staples`,
ligne « Stock consommé » retirée du rapport résumé. `styles.css` :
`.rp-pantry*`/`.rp-buy-btn`/`.rp-tag*`/`.rp-replan*` retirés ; `--rp-pantry`
renommé `--rp-amber` (encore utilisé par `.rp-promo-badge`, plus rien à
voir avec le garde-manger).

**Sections superseded, annotées sur place plutôt que réécrites** (même
convention que D15→D18) : « Pilote — périssables prioritaires ou
obligatoires » (le mécanisme `must_use`/`use_soon` entier disparaît, pas
seulement `use_soon` qui était déjà inerte) et « Écran Résultat — refonte
réelle » (tout le sous-thread garde-manger/« à acheter »/Replanifier).

**Vérifié contre PostgreSQL réel, en deux temps** : le bac à sable de cette
tranche n'avait initialement pas accès à Postgres (seule la vérification
statique ci-dessus — imports, `ast.parse` — était possible) ; l'utilisateur
a ensuite démarré sa base pendant la même session, ce qui a permis la
vérification réelle. Cycle de migration `upgrade head` → `downgrade base`
→ `upgrade head` propre sur `menu_test` : `downgrade base` vide les 4
schémas (`catalog`/`market`/`household`/`staging`), `upgrade head` les
recrée, `household.staple` présent, `pantry_stock`/`pantry_priority`
absents. **107/107 tests passés, 0 échec, 0 sauté** (venv dédié requis —
`python -m pytest` depuis l'environnement conda `base` échoue sur
`ModuleNotFoundError: No module named 'tests'`, exactement l'écueil déjà
documenté dans « Lancer / tester / seeder » ci-dessous, reconfirmé au
passage). `tsc -b`/`vite build` toujours propres.

**Sondé en direct contre la pile de développement de l'utilisateur**
(`docker compose up --build`, pas seulement la base de test) : le
conteneur `api` avait déjà rebuild et appliqué migration + seeding avec ce
code (`alembic current` → `f4b1a9d0c2e6` sur `menu_optimizer`,
`household.staple` contient `riz_basmati`/`huile_olive`/
`feuille_laurier`, exactement le seed principal mis à jour). Requêtes
réelles contre `http://localhost:8000` : `GET /api/staples` retourne les
trois essentiels seedés ; `POST /api/plan` retourne `needed_ingredients`
avec `riz_basmati.is_staple == true` et aucune clé `pantry_lines` ;
`POST /api/plan/{id}/finalize` avec `riz_basmati` confirmé disponible
retourne le **même menu** (`changes.added`/`removed` vides, la garantie
« finaliser ne change jamais les recettes » tient en pratique) et un
poste achats en baisse de 2,34 $, avec le riz effectivement absent de la
nouvelle liste d'épicerie ; `POST /api/plan/{id}/commit` fonctionne, et
un second `finalize` sur le plan commis est rejeté 409 comme attendu
(deux plans de test créés dans cette base au passage, id 287 non commis
et id 288 commis — aucune donnée de seed altérée). **Non vérifié** :
interaction en navigateur (rendu réel des écrans Essentiels/confirmation/
Résultat) — à faire manuellement avant de considérer cette tranche
pleinement terminée, le contrat HTTP sous-jacent est maintenant confirmé
correct.

## D19 — Sixième terme d'objectif : pénalité de gaspillage périssable (2026-08-12)

Suite directe de la tranche précédente : en discutant de l'utilité du terme
de récupération une fois le garde-manger retiré, l'utilisateur a demandé
explicitement d'ajouter un sixième terme qui pousse le solveur à utiliser un
ingrédient périssable plutôt que de le laisser en surplus — `perishability`
était chargé depuis le début mais jamais lu nulle part. Détail complet de la
formule, du raisonnement d'élimination (pourquoi σ_i ne peut pas porter
cette pénalité) et de la portée exclue : **D19, `docs/deviations.md`**
(nouvel écart explicite à la formule exacte de l'objectif de `docs/spec.md`
— jamais modifié lui-même).

**Piège réel, trouvé en testant, pas anticipé au plan approuvé.** Le plan
initial proposait de partager `w_i`/`_add_surplus` (le mécanisme du terme 4)
avec la nouvelle pénalité, en changeant seulement le signe dans l'objectif.
Testé en direct contre l'instance jouet (œuf forcé à périssabilité 1,0 via
`dataclasses.replace`) avant même d'écrire le test formel : **aucun effet**
— le solveur mettait systématiquement `w_i = 0`. Cause structurelle : `w_i ≤
approvisionnement − besoin` ne fait que plafonner `w_i` ; avec un
coefficient de pénalité à minimiser, rien ne force `w_i` à refléter le vrai
surplus, le solveur le laisse simplement à 0. Le crédit ne fonctionne que
parce que l'objectif *maximise* `w_i` (le pousse vers sa borne haute) — une
pénalité a besoin de l'inverse. Corrigé avec une variable et une contrainte
**séparées** (`solver/model.py::_add_perishable_waste`,
`gaspillage_i ≥ approvisionnement − besoin`, borne *basse* plutôt que
haute) — jamais un partage avec `w_i`. Détail complet dans D19.

**Calibration de la constante, elle aussi corrigée en testant.** La valeur
de départ proposée au plan (0,15, par analogie avec le plafond ≤ 0,8 de
σ_i) s'est révélée **sans aucun effet** sur la sélection de recettes du même
scénario jouet — noyée sous les termes achats/appétence. Un balayage direct
contre le solveur (0,15 → 20) a montré que l'effet n'apparaît qu'à partir
d'un ratio ≈ 1 et se stabilise dès 2. `PERISHABLE_WASTE_PENALTY_RATIO = 2,0`
retenu — vérifié, pas supposé.

**Vérifié** : test discriminant
(`test_perishable_penalty_shifts_recipe_selection`) confirme que le drapeau
change réellement la sélection (`omelette_toy` 1→3 portions pour absorber
le surplus d'œufs forcé périssable) et que les prix réels rapportés ne sont
jamais biaisés (450 c/douzaine dans les deux plans — contrairement au
mécanisme des essentiels, il n'y a même pas de substitution de prix ici).
Vérifié en deux temps, comme les tranches précédentes quand la base n'était
pas disponible d'emblée : **110/110 tests passés, 0 sauté** une fois
PostgreSQL de nouveau accessible (67 sans base + 43 dépendants de la base,
tous verts — aucune migration à revalider, ce chantier ne touche aucune
table). `tsc -b`/`vite build` propres.

**Sondé en direct contre la pile de développement de l'utilisateur**
(`docker compose up`, déjà reconstruite avec ce code) : `POST /api/plan`
avec `enable_perishable_penalty: true` contre `seed/main` (données réelles,
pas le jouet) retourne `objective_terms_cents.gaspillage = "20.25"`,
`flag_effects` liste bien `enable_perishable_penalty`, et `total` (−1571,75)
reconcilie exactement achats + déplacements + temps + gaspillage −
récupération − appétence (3773 + 0 + 0 + 20,25 − 0 − 5365) — la formule de
`total_cents()` est correcte de bout en bout, pas seulement au niveau du
jouet (plan de test id 357, non commis, aucune mutation). **Non vérifié** :
rendu réel en navigateur (nouveau segment « Gaspillage » dans la barre de
décomposition à 6 termes) — à faire manuellement.

**Limite documentée, hors périmètre de ce chantier** : `docs/spec.md`
(§ Fonction objectif) affirme que le crédit du terme 4 n'est honnête que si
le surplus est reporté vers un stock utilisable la semaine suivante —
mécanisme qui n'existe plus depuis le retrait du garde-manger (tranche
précédente). Le nouveau terme 6 n'en hérite pas (une pénalité n'a pas besoin
d'une réalisation future), mais la limite du terme 4 reste réelle,
consignée dans D19, pas corrigée ici.

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
`enable_multi_store` → `enable_time_cost` → `enable_staples` →
`enable_salvage` → `enable_perishable_penalty` (D19). Chaque drapeau seul doit produire un modèle résoluble
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
- ~~Le `print()` de debug dans `demand.py`~~ — **affirmation périmée,
  corrigée le 2026-08-11** : un audit dédié (grep systématique + historique
  git complet du fichier) n'a trouvé aucune trace d'un `print()` dans
  `demand.py`, ni aujourd'hui ni à aucun commit passé. L'affirmation
  ci-dessus semble avoir été inexacte dès l'origine, pas « depuis corrigée
  en silence ». Laissée biffée ici plutôt que supprimée, pour ne pas
  effacer la trace de l'erreur — voir aussi la « Leçon de méthode »
  plus bas, qui citait ce même exemple.
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

Le `print()` de debug dans `demand.py` (affirmation qui s'est révélée
elle-même périmée le 2026-08-11 — voir « Évaluation franche » ci-dessus ;
la leçon de méthode reste valable, l'exemple précis, lui, ne l'était pas)
et le `pyproject.toml` cassé (celui-là bien réel, corrigé en D14) ont tous
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

## Revue de l'artefact de devis, puis correction — 2026-08-13

L'utilisateur a demandé une revue de qualité de l'artefact publié
« Devis Souschef W33 », puis la correction de tout ce qui en sortait. Les
deux temps sont documentés dans
[`docs/revue-qualite-devis-2026-W33.md`](docs/revue-qualite-devis-2026-W33.md)
(diagnostic laissé intact + tableau des correctifs) et résumés dans
`docs/recipe-pricing-roadmap.md`.

**Ce que la revue a établi, chiffres à l'appui** : l'arithmétique de la page
était juste sur ses 1 513 lignes (coût = besoin × prix unitaire, somme =
coût consommé, /portion exact) et le bloc des 40 recettes curées était sain.
Les défauts étaient tous en amont ou dans la lecture : ail facturé à la tête
(73 lignes), décaissement calculé sur le plus gros format du magasin (un sac
de 50 lb pour 1 g), quantités importées à 1 g étiquetées « exact »,
confiance de recette inexplicable depuis ses lignes, cumul de rabais sans
signification additive, curation polluée par des produits composés.

**Décisions de conception à retenir** :
- **Deux questions, deux choix d'offre.** `recipe_costing.py` sélectionne
  désormais séparément l'offre qui valorise la consommation (meilleur prix
  unitaire, inchangé) et celle qui compose le panier
  (`min ceil(qté/format) × prix taxé`). Une seule sélection pour les deux
  rendait le décaissement fictif — c'était la cause, pas un symptôme
  d'affichage. Ratio médian acheté/requis 7,3× → 3,0×.
- **Une conversion déclarée s'applique aussi à dimension identique.**
  `maxi_capture.py` ne cherchait une règle que sur désaccord de dimension ;
  l'ail se vend « 5 unités » et se cuisine en gousses — deux comptes, même
  dimension. Aucune règle existante n'était dans ce cas, le changement
  n'affecte donc que l'ail (vérifié règle par règle avant édition).
- **La purge de curation devait précéder la conversion, pas la suivre.** Les
  naans et croûtons appariés à `gousse_ail` n'étaient inoffensifs que parce
  que la garde de dimension les rejetait. Ajouter la conversion en masse sans
  les rejeter d'abord aurait rendu le pain à l'ail moins cher que l'ail.
- **Un devis complet n'est pas un devis fiable.** `services/recipe_quality.py`
  nomme le défaut (quantité invraisemblable, ingrédient doublé, portions
  douteuses) sans rien corriger ni deviner : 59 devis sans réserve sur 129
  chiffrés, 0 recette curée touchée.
- **L'artefact devient reproductible.** `scripts/build_quote_artifact.py`
  rend la page depuis le seul rapport JSON, qui porte maintenant son index
  de produits. La page précédente était écrite à la main, donc invérifiable
  et non rejouable.

**Vérifié** : 172 tests passés, 51 sautés (PostgreSQL indisponible dans cette
session — aucun fichier touché ici n'en dépend) ; deux tests neufs
(`test_recipe_costing.py::test_checkout_buys_the_cheapest_basket...`,
`tests/test_recipe_quality.py`, 4 cas) ; rapport de devis reproduit à
l'identique avant modification, puis couverture mesurée **avec la
configuration temporairement remise dans son état d'origine** — 280/308
ingrédients et 129 devis complets dans les deux cas, aucun ingrédient perdu.
Artefact republié à la même URL.

**Non vérifié / restant** : rendu réel de la page dans un navigateur ; la
reprise des quantités fautives dans `seed/main/imported_recipes.json` (le
signalement existe, la donnée reste fausse) ; l'attribut « forme d'achat »
sur l'ingrédient canonique, qui seul empêchera durablement un cheddar
tranché sans gras ou un avocat surgelé de gagner un appariement au prix ; le
barème de taxes ne couvre que les rayons non ambigus. **`config/` et `data/`
ne sont pas suivis par git** — les décisions de curation modifiées ici ne
sont versionnées nulle part.

### Suite, même session : « 1 g » voulait dire « 1 unité »

L'utilisateur a relevé que beaucoup de lignes classées « 1 g » étaient en
fait « 1 unité ». Vérifié dans le corpus source : la projection amont
recopie le compte d'articles de la ligne (« 1 aubergine », « 12 ailes »)
dans un champ exprimé en grammes, et `import_cook_recipes.py` ne rappelait
sa propre résolution que si la valeur projetée était **absente** — une
valeur fausse mais présente passait intacte, et les équivalences déjà
curées n'étaient jamais consultées. 166 lignes dans ce cas.

**Portée plus large que le signalement de la veille** : le seuil de 5 g de
`recipe_quality.py` ne voyait pas « 3 poivrons » (3 g) ni « 12 ailes »
(12 g). Un seuil détecte l'absurde, pas le faux — la garde reste utile,
elle ne remplace pas la correction à la source.

`_count_copied_into_measured_field` rend la main à la résolution quand la
ligne se compte, que le canonique se mesure, et que la valeur projetée
**égale exactement** le compte brut (condition stricte, pour ne pas
écraser une quantité légitimement égale à son compte). 47 équivalences
ajoutées à `config/cook_recipe_curation.json` : 30 vérifiées au FCÉN 2026
(les canoniques portaient déjà leur code d'aliment dans
`canonical_ingredient_external_refs.json` — la source était là, personne
ne l'avait interrogée pour ça), 17 estimations déclarées avec leur raison
dans un nouveau bloc `grams_per_unit_provenance`. Deux lignes comptaient
des tortillas et non leur ingrédient de base : reclassées par
`canonical_overrides`, avec une conversion FCÉN pour la tortilla de maïs.

**Vérifié** : 166 lignes concernées, 0 non résolue ; 157 lignes modifiées
dans 86 recettes après réimport, `tags` seul autre champ touché ; coût
consommé réel de 63 devis en hausse de 215,92 $ au total ; 129 devis
complets et 281/309 ingrédients chiffrables (aucune perte) ; **103 devis
sans réserve contre 59** ; 172 tests passés, 51 sautés. Artefact republié.

### Troisième passe : rendements, doublons, identité du produit (2026-08-14)

« Fixons les problèmes maintenant » — les 79 défauts encore signalés. Deux se
sont révélés plus graves que leur étiquette, un troisième était un faux
positif de ma propre règle.

- **Le doublon d'ingrédient était une perte de données silencieuse, pas un
  défaut d'affichage.** `catalog.recipe_ingredient` impose l'unicité de
  (recette, ingrédient) et `_upsert` fait un `on_conflict_do_update` : pour
  28 recettes, la dernière ligne **écrasait** les précédentes en base pendant
  que le calcul de prix sur le JSON les additionnait. « Boulettes général
  Tao » : 405 g de fécule demandés, 62,5 g en base. Corrigé à l'import par
  addition (`_merge_duplicate_ingredients`), trace dans les tags. Leçon : deux
  chemins de lecture d'une même donnée finissent par se contredire, et c'est
  le plus silencieux qui gagne.
- **Le seuil « > 12 portions » était le mauvais critère.** Le corpus publie un
  rendement (« 20 boulettes », « 625 ml »), pas toujours des portions ; mais
  une tourtière à « 24 portion(s) » est légitime et le seuil la signalait à
  tort. La règle lit maintenant la **preuve** (`tags.servings_source`, ajouté
  à l'import) et non un nombre. Dix `serving_overrides`, chacun justifié,
  sous une convention écrite une fois.
- **La dernière quantité « invraisemblable » était exacte** (½ c. à thé de
  purée de chipotle = 3 g). La famille `conserves` mêle corps de recette et
  condiments : sortie de `BODY_FAMILIES`. Un faux positif sur une valeur juste
  coûte plus que la détection qu'il apporte.
- **Identité du produit (P6 de la revue) :** `IdentityRules` refuse qu'un
  produit composé tienne lieu d'ingrédient de base, sauf si le marqueur
  appartient à l'identité du canonique (« Pain au levain » reste un pain,
  « Sauce BBQ » est défendue par son alias). Trois marqueurs retirés après
  vérification parce qu'ils rejetaient de vrais aliments (« Bifteck
  sandwich », « Pêche beignet », « Soupe crème de champignons condensée »).
  125 produits écartés, zéro perte de couverture. La règle s'applique aussi
  aux appariements « approuvés » : les 6 831 approbations du manifeste
  viennent d'un traitement en lot, jamais d'une relecture une à une.
- **Un test que j'avais écrit a attrapé un vrai défaut de ma règle** :
  « Bagels » au pluriel échappait au marqueur « bagel ». Le matcher tolère
  maintenant le pluriel, et rien de plus — la sous-chaîne rejetterait
  « gaufrettes » ou « beignet ».
- **La même équivalence sert les deux côtés.** L'avocat n'était surgelé que
  parce que « Avocat Hass » était bloqué faute de conversion pièce → masse,
  alors que l'équivalence FCÉN existait déjà dans la curation des recettes.
  46 `product_conversions` générées **depuis les mêmes nombres et la même
  provenance** que les quantités de recette. Effet réel sur la sélection :
  avocat frais, mangue fraîche, mini-concombres, et la figue devient
  chiffrable.

**Vérifié** : 180 tests passés, 51 sautés ; **130 devis complets, 130 sans
réserve** (aucun défaut résiduel), 282/309 ingrédients chiffrables, un seul
encore bloqué par une dimension (`feuille_riz`). Artefact republié.
**Reste nommé** : l'attribut « forme d'achat » sur l'ingrédient canonique —
les marqueurs par ingrédient sont un palliatif vérifié cas par cas, pas un
modèle ; épinards et brocoli restent achetés surgelés sans que ce soit
déclaré.

### QA/QC du module de prix, puis les 15 correctifs (2026-08-16)

L'utilisateur a demandé une revue qualité du module de calcul du prix d'une
recette, puis la correction de tout ce qui en sortait, découpée en tickets.
Diagnostic complet dans
[`docs/qa-module-prix-recette-2026-08-16.md`](docs/qa-module-prix-recette-2026-08-16.md) ;
tickets dans `.scratch/qa-module-prix-recette/issues/` (15, en ordre de
dépendance) ; décisions de sémantique versées dans
[`docs/adr-recipe-pricing-semantics.md`](docs/adr-recipe-pricing-semantics.md),
qui passe de « accepté » à « révisé ».

**Le défaut le plus grave n'était pas dans le calcul.** `GET /api/recipe-quotes`
répondait 500 au premier appel dans la pile livrée : le chemin du fichier de
règles était calculé en remontant trois dossiers depuis le fichier source, ce
qui vise `/config` une fois le paquet installé — dossier absent de l'image, qui
ne copie que `backend/`. Et `config/` n'était versionné nulle part. Aucun test
Python ne pouvait attraper ça ; la garde vit donc aussi sur `docker-compose.yml`
(montage + `MENU_CONFIG_DIR`), exactement la leçon déjà consignée plus haut sur
les chemins que la documentation décrit mais que personne ne fait échouer exprès.

**Décisions de conception à retenir** :

- **Une seule sélection d'offre, pas deux.** La tranche précédente séparait la
  valorisation (meilleur prix unitaire) de l'achat (panier le moins cher). Les
  deux nombres finissaient par décrire deux produits différents : 532 lignes du
  rapport W33 valorisées sur un produit autre que celui acheté, et un coût
  consommé total **9,9 % sous le prix de tout panier réel** — pommes de terre
  valorisées au sac de 50 lb pendant qu'on achète 3 lb. La valorisation suit
  désormais le produit acheté ; le meilleur prix unitaire reste publié à part
  (`best_unit_price_cents`), sans prétendre être ce qu'on paie.
- **Un décaissement autonome décrit une course, pas une tournée.** Le panier se
  compose dans une seule bannière, la moins chère qui couvre tout ; quand aucune
  ne couvre tout, `basket_scope` vaut `multi_store` et le devis le déclare.
- **Deux nombres, deux confiances.** `consumed_confidence` et
  `checkout_confidence` : un produit au poids ne dégrade plus une valorisation
  exacte. Le test qui verrouillait l'ancien comportement a été mis à jour avec
  sa raison — c'était la spec qui n'était pas tenue, pas un accident.
- **Un prix de zéro est une donnée manquante.** Le filtre acceptait `>= 0`, donc
  une offre à zéro remportait toujours la sélection et rendait la recette
  gratuite en `exact`. Le garde-fou n'existait que dans l'adaptateur de capture,
  jamais dans le module qui déclare l'invariant.
- **Un seul résolveur de règles d'approvisionnement** (`services/supply_rules.py`,
  nouveau) : le calcul de prix ne faisait qu'un saut, l'audit de couverture
  itérait jusqu'au point fixe, et l'audit annonçait donc une couverture que le
  calcul ne savait pas livrer. Le parseur du fichier était en outre recopié dans
  trois appelants, et le troisième oubliait `source_qty_per_target_unit`.
  Vérifié sur données réelles : **129 = 129, zéro désaccord** entre les deux.
- **Les essentiels du ménage sont consommés mais pas rachetés.** Ils ne
  deviennent pas gratuits (ce serait la règle `essential`, réservée à l'eau) :
  ils restent valorisés et restent bloquants si aucun produit ne les vend. Lus
  dans `household.staple` par l'API et dans le seed par le script — jamais
  recopiés dans le fichier de règles, qui serait devenu une seconde source de
  vérité.
- **Deux faits faux retirés du catalogue.** Une bière au miel appariée à `miel`
  dans 8 recettes — elle perdait la valorisation mais gagnait la composition du
  panier, donc elle n'apparaissait que dans la liste d'épicerie, ce qui explique
  qu'elle ait survécu à la revue de la veille. Et une « demi caisse de figues »
  déclarée 50 g (une figue), soit 200 $/kg. La garde d'identité passe par le
  **rayon du détaillant**, pas par un mot du titre : un marqueur « bière »/« vin »
  sur le titre, essayé d'abord, rejetait à tort « Sauce barbecue avec bière
  Guinness », « Filets d'aiglefin en pâte à la bière » et « Vinaigre de vin
  blanc » — vérifié produit par produit sur les 8 044 du registre avant d'écrire
  la règle.
- **Une borne supérieure de vraisemblance, par famille et par portion.** Le
  contrôle ne voyait que les quantités trop petites : « 130 devis complets, 130
  sans réserve » cohabitait avec 2 kg de roquette et 375 g de basilic pour
  2 portions, et 2,2 kg de pain au levain pour 2 portions. Les normes sont calées
  au-dessus du 90ᵉ centile observé sur le corpus ; elles signalent exactement les
  4 quantités fautives connues, et rien d'autre.
- **Un correctif du plan a été abandonné après mesure.** Rendre le seuil bas
  inclusif (`<=` au lieu de `<`) attrapait « 5 tranches de pain » recopié en
  grammes, mais signalait aussi le zeste d'un citron (5 g, juste) et 5 g de
  fécule de maïs (2 c. à thé, juste) : deux faux positifs pour un vrai. Le seuil
  reste strict, la raison est écrite dans le code, et le pain fautif reste
  signalé par la borne supérieure sur trois autres ingrédients de sa recette.

**Autres correctifs de la tranche** : économies comparées au panier réellement
alternatif hors promo (et jamais négatives) ; déterminisme (départage explicite
+ `ORDER BY`, rapport identique octet pour octet sur deux exécutions) ; mode de
vente inconnu refusé au lieu d'être lissé en « acheter le besoin exact » ;
fenêtre de validité vide plus jamais publiée ; achat au poids arrondi à un pas
qu'un comptoir sait peser (« 0,003 kg d'ail » n'existe pas) ; `servings`
refusé sur une recette sans composante marginale — 121 des 161 recettes, pour
lesquelles il ne changeait que la division ; couche `services` en import
paresseux, pour que le module pur soit réellement importable sans SQLAlchemy
comme sa docstring le promet.

**Mesuré sur le rapport 2026-W33, avant/après, mêmes captures** : coût consommé
2 011,67 $ → 2 111,56 $ (valorisation au produit acheté) ; décaissement
4 586,89 $ → 4 067,93 $ (−11,3 %, essentiels) ; économies annoncées 374,03 $ →
214,29 $ (la référence gonflée disparaît) ; ratio décaissement/consommé médian
2,59 → 1,99 ; décimales filantes dans les unités achetées 46 → 0 ; devis avec
réserve 0 → 3 ; 129/129 paniers en magasin unique. Un devis perdu
(`figues_roties`), parce que `figue` n'a plus de produit chiffrable — la perte
est nommée, pas absorbée.

**Vérifié** : **229 tests passés, 51 sautés** (180 avant ce chantier + 49
nouveaux ; PostgreSQL indisponible dans cette session, aucun fichier touché ici
n'en dépend), `app.main` s'importe et expose la route, artefact de devis rendu
sans erreur depuis le rapport régénéré. **Non vérifié** : la route en conditions
réelles derrière `docker compose up` — Docker n'était pas disponible dans cette
session, la garde posée sur `docker-compose.yml` remplace le sondage, elle ne le
remplace pas.

**Revue de code après coup, quatre correctifs de plus.** Une passe `/code-review`
a trouvé quatre défauts réels dans ce chantier, chacun corrigé et verrouillé :

- **Le câblage rendait la tranche 12 inerte là où ça compte.**
  `run_weekly_catalogues.py` — le **seul** chemin qui écrit dans
  `market.product`/`market.price` — construisait ses deux adaptateurs sans
  `identity_rules` ni `tax_schedule`, que le rapport hors ligne leur passe
  pourtant. La bière au miel restait donc appariée au miel en base pendant que
  le rapport publiait des chiffres propres, et le vin y entrait détaxé. Aucun
  test Python ne pouvait l'attraper : les deux appelants sont corrects
  isolément, c'est leur **divergence** qui est le défaut —
  `tests/test_weekly_runner_wiring.py` compare donc les deux chemins entre eux
  (vérifié : le piège signale bien les deux mots-clés manquants sur la version
  d'origine).
- **La référence « prix régulier » shoppait dans un magasin que le panier n'a
  pas le droit de visiter.** Interaction entre les tranches 04 et 15 :
  `regular_totals` balayait tous les candidats alors que le panier payé est
  restreint à `basket_store`. On comparait une course à une tournée, et
  l'économie annoncée était systématiquement sous-estimée, souvent écrasée à 0
  par sa propre garde `max(0, …)`.
- **Le front-end lisait un champ que la tranche 09 venait de supprimer.**
  `Result.tsx` affichait `quote.confidence`, remplacé par les deux niveaux
  séparés ; `types.ts` déclarait un champ fantôme, donc TypeScript ne pouvait
  rien voir et l'écran imprimait la chaîne `undefined`. Ma vérification
  initiale s'était contentée d'un `grep` dont le motif ne pouvait pas
  correspondre à une déclaration nue — l'absence de résultat ne prouvait rien.
- **La tranche 10 cassait tout l'écran au lieu d'une ligne.** Le 422
  (`RecipeNotScalableError`) est atteint avec des données normales, `servings`
  étant le `x_r` du solveur ; un `Promise.all` nu effaçait alors le prix de
  **tout** le menu. Chaque devis encaisse maintenant son propre échec, et
  « prix incomplet » ne décrit plus les états « en cours » et « échoué », qui
  ont leurs propres libellés.

**Trouvé par la revue, hors périmètre de ce chantier, non corrigé** (défauts du
travail non commis des sessions précédentes, à traiter séparément) :
`services/planning.py:522` mélange `Decimal` et `float` sur les unités d'un
produit au poids — 500 sur `POST /api/plan` dès qu'un tel produit est en promo ;
le bloc d'exclusion `/maxi/alimentation/` de `retail_product_curation.py` est du
code mort (103 des 625 titres exclus deviendraient des liens valides — « Soda
gingembre » vers `gingembre_frais`) ; `poivron orange` est lié à
`tomate_orange` ; les règles « thym/aneth en pot » sont masquées par les règles
sèches ; `_MONEY` de `maxi_web.py` n'a pas d'ancre de devise, donc « 2/5,00 $ »
est lu 2,00 $ ; deux troncatures silencieuses de pagination dans
`superc_web.py` ; et `ports/dto.py` change `payload_fingerprint`, ce qui fera
réatterrir tout l'historique une fois dans `staging.raw_offer`.

**Vérifié après correctifs** : **234 tests passés, 51 sautés** ; `tsc -b` et
`vite build` propres ; rapport régénéré sans erreur.

## Le vrai catalogue atteint le planificateur (2026-08-19)

**Symptôme rapporté.** « Les recettes que cette app me propose sont trop
cheap. » Le corpus n'était pas en cause : 121 des 161 recettes en base viennent
de Ricardo, Bon pour toi et Jean-Philippe (lasagne maison, bœuf braisé à
l'italienne, pad thaï, effiloché de porc). Aucune n'était atteignable.

**Cause mesurée, contre PostgreSQL réel.** `market.product` contenait 83 lignes
— le catalogue de démonstration de `seed/main/products.json`, fabriqué par
`generate_seed.py` sur un sous-ensemble figé de **23 ingrédients**. Le filtre
dur « ingrédient sans aucun produit prixé » (`services/prefilter.py`) élimine
toute recette dont un seul ingrédient manque. Survivantes : **41 sur 161, dont
40 étaient les 40 recettes de démonstration écrites à la main** (chili aux
lentilles, omelette au fromage, potage de carottes…). Le catalogue réel existait
pourtant — `data/catalogue-registry/superc.json`, 8 044 produits, 510
ingrédients appariés — mais n'était lu que par `quote_recipes.py` et l'audit de
couverture. Le module de prix publiait 2 165 produits ; le solveur en voyait 83.

**Ce qui a été fait** (détail et rationnel : `docs/deviations.md`, D24 et D25) :

- `app/ingestion/catalogue_sources.py` — fabrique **unique** des adaptateurs de
  bannière, plus la période de circulaire jeudi-mercredi qui existait en deux
  exemplaires. Les quatre appelants y passent.
- `scripts/import_captured_catalogue.py` — importe une semaine de captures déjà
  sur disque, sans rescraper. `scripts/import_maxi_catalogue.py` est retiré :
  il écrivait en base *sans* `product_conversions`, `identity_rules` ni
  `tax_schedule`, exactement le défaut corrigé une session plus tôt pour la
  collecte hebdomadaire.
- `tests/test_weekly_runner_wiring.py` change de nature : au lieu de comparer
  deux copies entre elles, il vérifie que la fabrique arme les trois règles
  **et** qu'aucun script ne construit un adaptateur directement. Un cinquième
  appelant divergent n'est plus une chose qu'on oublie de tester.
- σ recalibré pour `gousse_ail` et `feuille_laurier`
  (`generate_seed.py::REAL_PRICE_FLOOR_CENTS`) : dérivé des prix de
  démonstration, il dépassait 0,8·min du vrai catalogue et l'assertion 1
  **refusait tout plan** dès l'import.
- Préfiltrage : une recette dont le besoin est identiquement nul est écartée
  (étape `besoin_non_nul`), au lieu d'être servie gratuitement.

**Mesuré après import** (Super C 640, 2026-W33, `market.product` 83 → 2 248,
ingrédients prixés 23 → 469) : recettes franchissant le préfiltrage **41 → 92**.
Avant l'import, à la date du jour, le compte tombait à **0** — les prix de
démonstration expirent le 16 août et rien ne les remplaçait ; l'application ne
pouvait plus proposer aucun menu.

**Ce qui n'est PAS résolu — le menu reste le même.** Le catalogue était une
condition nécessaire, pas suffisante. Trois obstacles restent, tous mesurés :

1. `services/appetence.py` lit `tags["cuisine"]` / `tags["saison"]` (singulier)
   alors que les 121 recettes importées portent `cuisines` / `categories`
   (pluriel, listes). Elles restent toutes à la base 1,30 $ quand une recette de
   démonstration atteint 2,15 $ (tag aimé + saison).
2. Le crédit d'appétence plafonne à 2,65 $/portion alors que l'écart de coût
   entre un plat de lentilles et un braisé le dépasse largement. Le solveur
   minimise donc le coût, en mode `objective` comme en mode `constraint`.
   Vérifié : magasin Super C imposé, `enable_batch_fixed_cost` actif, menu =
   chili aux lentilles, galettes de lentilles, riz frit, sauté de tofu, à
   1,00 $/portion — identique avec `appetence_mode: "objective"`.
3. ~~Le profil habite Montréal, les bannières capturées sont à Québec~~ —
   **corrigé le même jour** (D26) : `select_stores` ne retient plus qu'un
   magasin ayant au moins un prix valide à la date du plan, et l'assertion 4 se
   juge sur les magasins réellement utilisables au lieu du marché entier. La
   configuration par défaut passe de `Infeasible` à `Optimal` (Super C,
   25,32 $), et un magasin imposé sans prix rend un 422 qui le nomme au lieu
   d'une infaisabilité muette accusant `enable_variant_exclusion`.

**Vérifié** : 332 tests passés contre PostgreSQL 18 réel ; `quote_recipes.py` et
`audit_recipe_pricing_coverage.py` reproduisent après migration leur chiffre de
référence documenté (129/161 devis complets, 281/309 ingrédients prixés) ;
un plan `Optimal` généré de bout en bout depuis les prix Super C importés.
**Non vérifié** : la pile derrière `docker compose up` (Docker absent de cette
session) et le front-end, non touché.


## Plancher de dépense d'épicerie (2026-08-20)

**Demande.** « Ça prend toujours les trucs les moins chers, comment faire pour
que mon panier atteigne un prix minimum, ex. 60 $ ? »

**Ce qui existait déjà.** Le plancher d'appétence (`appetence_u_min_dollars`)
répond à la question, mais en points, pas en dollars. Mesuré sur `seed/main`,
semaine du 13 août : U_min = 50 → 32,07 $ ; U_min = 70 → **62,77 $** et un menu
de 10 plats (tacos au bœuf, chili con carne, dahl) ; U_min = 90 → infaisable. Le
levier était donc là, mais la correspondance points → dollars change à chaque
circulaire.

**Ajouté** (D27, `docs/deviations.md`) : `min_grocery_spend_cents_cad` sur le
profil, résolu par `services/params.py` comme K/R_min/α/ε/U_min, contraint par
`_add_min_spend_constraint` **sur la même expression que le terme d'achats de
l'objectif** (avec `enable_staples`, un recalcul parallèle divergerait de
plusieurs dollars). Champ « Épicerie minimum ($) » dans Ménage › Préférences.

**Assertion 0.** Un plancher de dépense n'achète un meilleur menu que si
quelque chose récompense un meilleur menu. En mode d'appétence « constraint »,
l'appétence quitte l'objectif : plus rien ne départage les façons de dépenser,
et le chemin le moins cher vers le montant devient le surplus.
`validate_problem` refuse donc la combinaison
(`SpendFloorWithoutRewardError`). Numérotée 0 : elle ne lit aucune donnée,
seulement les paramètres résolus, donc elle passe avant les six assertions de
la spec — son échec nomme un réglage, pas un catalogue.

**Limite mesurée, pas supposée.** J'attendais qu'un plancher démesuré soit
infaisable. Faux : rien ne borne la quantité achetée par le haut, donc le
solveur atteint n'importe quel montant en achetant plus. Ce qui sature, c'est
l'appétence. Part de la quantité achetée non consommée : 19,4 % sans plancher
(formats d'emballage), 28,6 % à 60 $, 32,2 % à 90 $, 69,0 % à 200 $, 88,8 % à
600 $ — pendant que l'appétence passe de 54,50 à 67,30 puis 71,40 et n'augmente
plus. C'est un budget **dans sa plage utile**, du gaspillage au-delà. Aucune
borne codée en dur : elle dépend du catalogue de la semaine. C'est la mesure
qui est verrouillée (`tests/test_min_grocery_spend.py`).

**Vérifié** : 339 tests contre PostgreSQL 18 réel, `tsc -b` propre, et le
parcours complet dans l'interface — plancher posé à 60 $ dans Ménage ›
Préférences, plan généré, écran final à **60,00 $**, 10 plats, 16 articles.
Le montant rapporté peut diverger du plancher de moins d'un cent (contrainte en
flottants PuLP, rapport recalculé en `Decimal`) : mesuré 5 999,42 contre 6 000.


## Bouton « Rafraîchir les prix Super C » (2026-08-20)

**Demande.** Un bouton dans le front-end qui lance le script de mise à jour des
prix Super C.

**La tension à nommer avant de coder.** D23 et `ports/circular.py` interdisent
la collecte dans une requête HTTP, et une passe Super C dure une trentaine de
minutes. Un bouton ne peut donc ni collecter, ni attendre. Résolu en démarrant
un **processus détaché** : `POST /api/price-refresh` répond 202, `GET` rapporte
l'état. L'invariant tient au sens propre, et la garde est posée sur les *imports*
du module de lancement — un `httpx.get` ajouté un jour passerait tous les tests
fonctionnels tout en violant l'invariant.

**Deux processus.** L'API démarre un superviseur qui lance le collecteur, attend
et écrit le verdict. Sans lui, une collecte réussie serait indistinguable d'un
plantage dès que l'API redémarre pendant les trente minutes — ce que `--reload`
fait à chaque édition de fichier. L'état est un fichier JSON, jamais de la
mémoire de processus.

**Deux défauts trouvés en exécutant, pas en relisant** (détail : D28) :

- `os.kill(pid, 0)`, le sondage POSIX habituel, est traduit par CPython sous
  Windows en `TerminateProcess(handle, 0)` : il **tuait** la collecte en la
  faisant passer pour réussie (code 0). Remplacé par
  `OpenProcess`/`WaitForSingleObject`, avec son test.
- Le journal s'affichait « [D�marrage] Superc en parall�le » à l'écran : un
  enfant Python écrit sous Windows dans la page de codes de la console.
  `PYTHONIOENCODING`/`PYTHONUTF8` imposés à l'enfant.

**Refusé volontairement** : Maxi (fenêtre de navigateur visible + vérification
humaine — 422 avec la raison), la mise en file (409 — deux collectes doublent la
cadence vue par le détaillant), et toute progression fabriquée à côté de celle
du collecteur. **Absent, à assumer** : aucune annulation depuis l'écran ; un
clic lance trente minutes qu'il faut arrêter en ligne de commande.

**Vérifié en exécutant** : collecte réelle lancée depuis l'API (202), doublon
refusé (409), Maxi refusée (422), et le journal du collecteur remonté à l'écran
(« [Super C 01/35] fruits-et-legumes/fruits », puis la progression page par
page).


## Le bouton doit mettre la base à jour (2026-08-20, suite)

**Défaut livré, puis corrigé.** Le bouton lançait `run_weekly_catalogues.py
--apply`, qui lève `RuntimeError` dès qu'un rayon est tronqué — **avant** son
bloc `if args.apply:`. Le 20 août, 17 rayons sur 35 paginaient moins que Super C
n'annonçait : la passe ne écrivait pas une ligne. J'avais livré un bouton qui
faisait fidèlement ce que fait la ligne de commande, y compris ne rien mettre à
jour, et je l'avais rapporté comme tel plutôt que corrigé.

**Correction.** Superviseur en deux phases : collecte SANS `--apply` (sa garde
sur les captures tronquées reste vraie pour la ligne de commande et pour le
registre), puis `import_captured_catalogue.py --apply` qui lit les dossiers de
capture sans se soucier de leur complétude. C'est l'import qui décide de l'état,
parce que c'est lui qui écrit. `succeeded` + `collection_complete: false` est un
état légitime et distinct — « Prix mis à jour — capture partielle ».

**Vérifié en exécutant** : import lancé sur les captures partielles du jour →
1 545 produits, 5 966 prix, nouvelle fenêtre 2026-08-20 → 26, `market.product`
2 248 → 2 267, et la date du jour passe de « non couverte » à 1 545 prix
valides. 13 tests sur ce chemin, dont celui qui interdit `--apply` sur la phase
de collecte.


## Date de la dernière collecte à l'écran (2026-08-20)

**Demande.** « Il faudrait que ça te dise quand est-ce que le dernier scrapping
a été fait. »

**Le piège évité.** La réponse facile était `started_at` de l'état du bouton.
Elle aurait répondu « jamais collecté » à qui lance `run_catalogues.cmd` — le
raccourci livré du dépôt — juste après une passe complète. La date est donc lue
du **nom des dossiers d'exécution** (`run-<AAAAMMJJ>T<HHMMSS>Z`), que le
collecteur écrit lui-même : la seule trace indépendante du chemin de lancement
(`capture_layout.last_capture_at`).

**Mesuré avant de choisir la source** : `market.price` n'a aucun horodatage, et
`market.product.updated_at` ne bouge que sur une insertion — l'upsert brut
(`pg_insert().on_conflict_do_update`) ne déclenche pas le `onupdate` de l'ORM.
Ni l'un ni l'autre ne pouvait répondre « quand la base a-t-elle été écrite ». La
fraîcheur affichée est celle de la collecte, ce que la question posait.

**Séparé volontairement** : la date de collecte (toujours visible, lue du
disque) et le verdict de la dernière mise à jour (son propre panneau). Une passe
tronquée compte comme une collecte — « quand a-t-on scrapé » n'est pas « quand
a-t-on réussi ». Défaut assumé et constaté : le panneau de verdict peut afficher
« La mise à jour a échoué » devant une base à jour, si celle-ci a été écrite par
un autre chemin.

**Vérifié à l'écran** : « Dernière collecte Super C : 20 août à 08 h 56 — il y a
2 h », affichée aussi à l'état `idle`. Tests : `test_capture_layout.py` (noms
malformés ignorés, suffixe libre toléré, absence rapportée comme absence) et
`test_price_refresh.py` (la date survit à un état de bouton vide).


## Le verdict périmé de la mise à jour (2026-08-20)

**Signalé deux fois par l'usager** : « La mise à jour a échoué — démarrée à
08 h 56 » restait affiché devant une base à jour. Le verdict était vrai, sa
pertinence avait expiré, et sa formulation le faisait lire comme l'état courant
du catalogue.

`DELETE /api/price-refresh` + bouton « Masquer » (409 si une mise à jour tourne :
pas encore de verdict). Le journal est conservé. Libellé corrigé en « Dernière
tentative : échec ».

**Écarté** : l'expiration après N heures (délai arbitraire ; le moment où une
nouvelle cesse d'être utile appartient au lecteur) et la détection d'une écriture
en base par un autre chemin (`market.price` n'a aucun horodatage — la
comparaison serait fondée sur rien).

**Leçon.** J'avais qualifié ce comportement de « défaut d'affichage assumé » dans
D28 et je l'avais laissé tel quel, en l'expliquant. Il a fallu que la question
revienne pour que je le corrige. Un défaut qu'on documente reste un défaut :
l'expliquer n'est pas le traiter.

**Vérifié à l'écran** : verdict présent, clic sur « Masquer », verdict parti, et
la ligne de fraîcheur (« Dernière collecte Super C : 20 août à 08 h 56 — il y a
2 h ») conservée — elle vient du disque, pas de l'état effacé.


## Teneurs FCÉN en base — premier étage du calcul nutritionnel (2026-08-20)

**Demande.** « Calculer les macros et les calories de chaque repas à partir des
données fédérales. » Périmètre décidé avec l'utilisateur : énergie + trois
macronutriments ; refuser un total tant qu'une ligne d'ingrédient ne résout pas
(discipline de `recipe_costing`) ; affichage seulement, aucune contrainte
solveur — donc aucun nouvel écart à `docs/spec.md`.

**Ce que la mesure a renversé avant d'écrire une ligne de code.** Le FCÉN était
déjà importé, mais seulement pour l'identité (`Food_Name.csv`,
`CNF_Food_Group.csv`). Les fichiers de teneurs dorment dans la même archive
depuis le début. Le vrai obstacle n'est pourtant pas là :

- Énergie (208) et les trois macros (203/204/205) sont présentes pour
  **5 993 aliments sur 5 993**. La donnée fédérale ne manque jamais.
- Le pont manque. **727 des 1 066 ingrédients canoniques** portent une
  référence `cnf` — et les **727 viennent tous d'événements de curation**
  (`create_variant`/`attach_existing`), c'est-à-dire d'ingrédients nés *du*
  FCÉN. Les 339 jamais touchés par la curation sont le socle écrit à la main,
  et c'est là que vivent `oignon_jaune`, `oeuf`, `sel_table`,
  `farine_tout_usage`, `bouillon_poulet`, `beurre`, `lait_non_precise`, `eau`.
- Conséquence mesurée sur les 161 recettes : **0 entièrement résolvable**.
  941 des 1 441 lignes d'ingrédient sans référence `cnf`, 82 en unité de
  compte sans masse, 14 en volume sans densité. 234 ingrédients distincts à
  régler ; les plus bloquants sont `gousse_ail` (68 recettes),
  `bouillon_poulet` (43), `oignon_jaune` (35), `oeuf` (32), `sel_table` (29),
  `farine_tout_usage` (26).

**Livré dans cette tranche (étage 1 seulement).** Trois tables
d'atterrissage (migration `a3e7c1f9b204`) : `staging.cnf_nutrient_name`,
`staging.cnf_nutrient_amount` (teneur **par 100 g comestibles**, l'unité est
dans le nom de la colonne), `staging.cnf_measure_weight`.
`app.ingestion.cnf` gagne `parse_cnf_nutrients`/`upsert_cnf_nutrients`/
`import_cnf_nutrients` et un drapeau `--tables {identity,nutrients,all}` dont
le défaut `identity` **préserve exactement** le comportement historique.

**Décisions de conception à retenir** :

- **Aucune conversion à l'atterrissage.** L'unité reste le libellé fédéral
  (« kilocalorie », « Gram »), la précision reste `Numeric(14, 9)` — les
  teneurs publiées vont jusqu'à 9 décimales. Convertir ici aurait enterré le
  choix dans la couche qui a le moins le droit de le faire.
- **Le périmètre de nutriments est un paramètre, pas un schéma.**
  `RETAINED_NUTRIENT_CODES` filtre à l'import (23 972 teneurs au lieu de
  565 409). L'élargir est un rejeu, jamais une migration.
- **`cnf_measure_weight` importe les trois types de mesure**, avec
  `SERVING_MEASURE_TYPE_CODE = "6"` pour distinguer les masses de service des
  portions non comestibles (`3`) et des rendements (`9`). Les 4 716 lignes à
  0 g de l'archive 2026 sont **toutes** de type `3` — vérifié, pas supposé :
  une masse de service à 0 g convertirait « 1 gousse » en rien.
- **Une couverture partielle se rapporte, ne se comble pas.**
  `food_codes_missing_some_retained` vaut `()` sur l'archive 2026 ; une
  édition future qui régresserait le dirait au lieu de produire des totaux
  silencieusement incomplets plus loin.
- **Ces trois tables ne portent aucune décision humaine**, contrairement à
  `cnf_food_candidate` et son `curation_status` : l'upsert réécrit donc tous
  les champs hors clé depuis l'archive. Verrouillé par un test qui édite une
  teneur à la main et vérifie qu'un rejeu la restaure.

**Un cas réel que la vérification statique n'avait pas vu.** Ma passe
d'invariants avait contrôlé l'intégrité des `Food_Code` (parfaite) mais pas
celle des `Measure_Code` : le premier import réel a échoué sur
`Measure_Code inconnu 1116 pour l'aliment 1728`. Une ligne sur 29 868 —
« Pêche, crue », mesure de service de 175 g — référence un code absent de
`Measure_Name.csv`. Le fichier fédéral est incohérent avec lui-même, et ce
n'est pas réparable ici. Arbitré : le poids en grammes est le fait utile et il
est présent, donc la ligne entre avec ses libellés à `NULL` (colonnes rendues
nullables, jamais un libellé inventé) et le compte remonte à chaque import
(`measures_without_label`). Un `Measure_Type_Code` inconnu, lui, reste refusé :
sans type, impossible de distinguer une masse de service d'un poids de pelure.

**Défaut préexistant corrigé au passage**, sans rapport avec ce chantier :
`tests/test_pure_pricing_module_boundary.py::test_the_guard_itself_bites`
échouait. Le piège mordait réellement (`ImportError` levée, code de retour 1) ;
seule l'assertion sur son message tombait, parce qu'un enfant Python écrit sous
Windows dans la page de codes de la console et que « refusé » revenait
« refusÃ© » au parent. Exactement le défaut déjà consigné en D28 pour le journal
du collecteur, et le même correctif (`encoding="utf-8"` +
`PYTHONIOENCODING`/`PYTHONUTF8` imposés à l'enfant).

**Vérifié contre PostgreSQL réel** : cycle `downgrade -1` → `upgrade head`
propre ; **372 tests passés, 0 échec, 0 sauté** (359 avant ce chantier + 13
nouveaux dans `tests/test_cnf_nutrient_import.py`). Import de l'archive réelle
exécuté, pas simulé : 4 nutriments retenus, **23 972 teneurs**, **29 868 poids
de mesures dont 21 207 de service**, 5 993 aliments complets, 0 partiel, 1 sans
libellé, `sha256=F5FAAD89…`. Rejeu immédiat : comptes identiques (4 / 23 972 /
29 868), idempotence constatée et non affirmée. La donnée qui débloque le pire
goulot est bien là : aliment 2394 « Ail, cru », **1 gousse = 3,0 g**.

**Importé dans `menu_test`, PAS dans la base de dev.** La commande à lancer
contre `menu_optimizer` reste à faire, après `alembic upgrade head` :
```bash
cd backend
python -m app.ingestion.cnf --archive ../data/cnf_fcen_all-files-data_2026.zip --tables nutrients
```

**Reste à faire à l'issue de cette tranche** — voir la section suivante, qui
livre les étages 2 à 4.

**Hypothèse assumée** : les quantités de recette sont des quantités d'achat
crues, donc l'appariement vise la forme **crue** du FCÉN. La perte d'eau à la
cuisson ne change ni les calories ni les macros — mais le gras égoutté d'un
bœuf haché rissolé et l'huile absorbée en friture, oui. Limite réelle, nommée
dans la docstring de `services/recipe_nutrition.py`, pas lissée.


## Une recette rend ses macros par portion, ou refuse en nommant ses trous (2026-08-20)

**Livré.** Le chemin complet, du règlement à l'écran.

```
config/nutrition-rules.json          règlement versionné (apports négligeables + aliment retenu)
services/nutrition_rules.py          lecture et résolution du règlement — pur
services/recipe_nutrition.py         calcul par portion — pur, calqué sur recipe_costing
services/recipe_nutrition_facts.py   façade SQL (recettes + canon + pont FCÉN + teneurs)
services/recipe_nutrition_coverage.py audit de couverture — pur, appelle le calcul
services/recipe_scaling.py           rendement et besoin par lot — un seul lecteur, partagé
services/confidence.py               échelle de confiance — un seul lecteur, partagé
GET /api/recipe-nutrition            route de transport, 404/422/503 nommés
scripts/audit_recipe_nutrition_coverage.py   audit hors base (seed + règlement + archive)
Écran Résultat › détail recette       « Valeur nutritive par portion », ou le refus
```

**Trois refus qui font la valeur du module**, tous exercés par des tests :

1. **Aucun total partiel.** Une ligne non résolue met les quatre nombres à
   `null` d'un coup et la recette nomme ce qui bloque, avec une raison par
   ingrédient (`no_cnf_food`, `ambiguous_cnf_food`, `missing_density`,
   `missing_grams_per_unit`, `over_negligible_ceiling`…). Chaque raison est une
   file de travail différente, donc l'audit les compte séparément.
2. **Une borne, jamais un zéro.** Un apport déclaré négligeable compte pour
   zéro *et* remonte la borne de l'erreur consentie
   (`kcal_error_bound_per_serving`, affichée en « ± »). Détail en D29.
3. **L'aliment FCÉN retenu se déclare.** 26 ingrédients portent plusieurs
   aliments, et `mais` en portait un qui nomme des pâtes. Détail en D30.

**Un point d'architecture à connaître** : la façade **lit** `staging.cnf_*`, en
lecture seule, comme `services/offer_resolution.py` lit déjà
`staging.raw_offer`. L'invariant que la règle protège est « ne jamais écrire
dans `staging`, ne jamais court-circuiter la normalisation », pas « ne jamais
lire ». Détail et solution de rechange écartée en D31.

**Vérifié contre PostgreSQL réel et l'archive fédérale réelle** (pas de
simulation), base de dev migrée en `a3e7c1f9b204` puis importée :
5 993 candidats, 4 nutriments, 23 972 teneurs, 29 868 poids de mesures,
`sha256=F5FAAD89…`.

`GET /api/recipe-nutrition?recipe_id=ricardo_5899_salsa_d_avocat_et_de_mais_grille` :

```
Salsa d'avocat et de maïs grillé | 10 portions | complete | confiance: estimated
  48,6 kcal  ± 0,8   P 1,0 g   L 3,1 g   G 5,2 g
  mais              18,0 g   computed    15,5 kcal   2388 « Maïs sucré, jaune, cru » (correction)
  avocat            20,1 g   computed    32,2 kcal   1511 « Avocat, cru, toutes variétés » (primary)
  jus_lime           3,0 ml  negligible   0,0 kcal   borne 0,8 kcal (FCÉN 1594)
  coriandre_fraiche  1,0 g   computed     0,2 kcal   2067
  oignon_vert        1,5 g   computed     0,5 kcal   2144 (primary)
  piment_jalapeno   0,75 g   computed     0,2 kcal   4860
```

Et le refus, sur `chili_lentilles` : `status=incomplete`,
`kcal_per_serving=null`, quatre manques nommés (`oignon_jaune`,
`lentille_verte`, `tomate_conserve` sans aliment FCÉN ; `gousse_ail` sans masse
par unité) — alors que deux de ses six lignes se calculent parfaitement. Le
refus porte sur le total, pas sur la preuve.

**Couverture réelle, mesurée par l'audit** (`python
scripts/audit_recipe_nutrition_coverage.py`, sans base) :

- **1 recette calculable sur 161.** C'est le point de départ honnête, et
  l'audit dit exactement ce qu'il faut curer pour le déplacer.
- 393 lignes calculées, 184 déclarées négligeables, sur 1 441.
- 215 ingrédients bloquants : 200 sans aliment FCÉN, 5 en volume sans densité,
  5 au-delà du plafond déclaré négligeable, 4 ambigus, 1 compté sans masse.
- **215 ingrédients à curer pour tout couvrir.**

**Ce que la mesure a renversé sur l'ordre de curation.** Le classement par
fréquence — l'ordre que la tranche précédente supposait — ne donne aucun
palier : la couverture avance d'environ 0,8 recette par ingrédient curé, du
premier au deux-centième, parce que les recettes ont de longues listes et qu'il
leur faut presque tout. Le classement par **recettes complétées** (couverture
d'ensemble, gloutonne) change l'échelle : 33 ingrédients rendent 50 recettes
calculables, 36 en rendent 60, là où les 36 plus fréquents en rendent 45.
L'audit publie cette courbe-là. Corollaire : `gousse_ail` reste le plus
bloquant (68 recettes) mais ne complète rien à lui seul.

**Reste à faire, dans l'ordre — et l'ordre a changé.**

1. **Le lot d'amorçage** : les ~33 ingrédients que la courbe de déblocage place
   en tête (`tomate_conserve`, `boeuf_hache_maigre`, `oignon_jaune`,
   `lentille_verte`, `poulet_cuisse`, `riz_basmati`, `creme_35`, `beurre`…).
   Ils traversent les familles : c'est le prix à payer pour que des recettes
   entières deviennent calculables tôt.
2. `grams_per_unit` pour les 12 ingrédients comptés du corpus, dérivé de
   `cnf_measure_weight` type 6 — la donnée est là (aliment 2394 « Ail, cru » :
   1 gousse = 3,0 g). La convention `verified_grams_per_unit` /
   `grams_per_unit_provenance` de `config/cook_recipe_curation.json` est déjà
   lue par la façade; aucun des 12 n'y figure. `units.py::convert_qty` reste
   inchangé et continue de refuser count↔g.
3. La densité des 55 ingrédients en volume, dérivée des mesures FCÉN portant un
   volume explicite en millilitres — avec le garde-fou contre la densité de
   tassement (65,089 g pour 100 ml de maïs en grains, ce n'est pas une densité).
4. Les 10 placeholders `_non_precise` réellement utilisés par les recettes
   (`beurre_non_precise`, `lait_non_precise`, `poulet_non_precise`,
   `riz_non_precise`, `sucre_non_precise`, `champignon_non_precise`,
   `basilic_non_precise`, `persil_frais_non_precise`, `cumin_non_precise`,
   `poivre_non_precise`) résolus vers un ingrédient réel, et les
   variétés absentes du FCÉN (basmati, dijon) déclarées en `substitution` avec
   leur justification.
5. Le reste de la curation, par familles — après le lot d'amorçage, l'ordre ne
   paie plus, et regrouper par famille économise le contexte du relecteur.
6. Un test qui verrouille la couverture atteinte, comme l'audit de prix
   verrouille son 129/161.


## Le pont canonique → FCÉN : proposer, dériver, et refuser (2026-08-20, suite)

**Livré.** Trois outils, tous exécutés sur l'archive réelle, aucun n'écrivant
de décision tout seul.

```
services/cnf_match_proposal.py     propose des aliments FCÉN par jetons — pur
services/fcen_measures.py          dérive masse/unité et densité, ou refuse — pur
scripts/propose_cnf_matches.py     manifeste de candidats, file d'attente = l'audit
scripts/derive_fcen_measures.py    propositions de masses et de densités
scripts/nutrition_inputs.py        chargeurs partagés (seed + archive), un seul lecteur
config/nutrition-rules.json        + 9 substitutions déclarées (règlement 2026-08-20b)
config/cook_recipe_curation.json   + gousse_ail = 3 g par gousse, avec provenance
```

**Le manifeste d'appariement.** 204 ingrédients appariables (ceux dont le
blocage est un appariement, pas une mesure), **194 avec au moins un candidat**,
9 sans aucun. Cinq candidats classés par ingrédient, plus les rejets **avec leur
motif** — un curateur doit pouvoir constater qu'un aliment a été écarté et
pourquoi. La file d'attente vient de l'audit de couverture, donc du calcul :
`oignon_jaune` (35 recettes) avant `orzo` (2).

**Quatre défauts trouvés en exécutant, pas en relisant** (détail en D32, tous
consignés en test) : la ligature « œ » qui ne se décompose pas — « Œuf de
calibre gros » s'appariait sur le mot « gros » à « Porc, morceau de gros, gras
de dos, cru », 812 kcal/100 g ; les marques de cuisson comparées par préfixe —
« Poulet **à griller** » est une catégorie d'oiseau, et « cuisse » se lisait
comme « cuit » ; la congélation lue comme une cuisson, alors que le FCÉN écrit
« frais ou congelé, cru » pour un état d'achat ; et les parenthèses, où le
fichier fédéral met systématiquement le mot qui discrimine — « Confiseries,
sucre, brun **(cassonade)** », « Pâtes **(spaghetti, macaroni)**, enrichi, sec »
étaient rejetés comme plats composés.

**Honnêtement mesuré, sur les 25 ingrédients les plus bloquants** : le premier
candidat est défendable **19 fois sur 25**. Les six autres échouent soit sur une
variété que le canon ne nomme pas (œuf de poule contre œuf de cane, lait 3,25 %
contre lait écrémé), soit sur un mot que le fédéral écrit autrement (« soya »
pour du soja). Dans tous ces cas le bon aliment est **dans les cinq candidats**.
C'est le travail d'une session de revue, pas un poids à mieux régler : le module
ne prétend pas choisir une variété que son entrée ne nomme pas.

**Dérivation des mesures.** `gousse_ail` = **3,0 g par gousse** (FCÉN 2394,
mesure de service type 6), appliqué : **68 lignes de recette passent de
bloquantes à calculées** et la raison `missing_grams_per_unit` disparaît de
l'audit. **Six densités appliquées** (canola 0,921, dijon 1,040, quatre
vinaigres de 1,010 à 1,078), provenance en commentaire à côté de chaque chiffre
dans `scripts/catalog_seed_data.py` : `missing_density` disparaît à son tour,
**200 ingrédients bloquants** et **508 lignes calculées**. L'huile d'olive garde
son 0,91 écrit à la main, que la dérivation confirme à 0,913. Aucun effet sur
les prix, vérifié en base : les 26 produits de ces six ingrédients sont tous
vendus en volume, donc aucune conversion masse↔volume ne lit leur densité.

**Rectification.** Une tranche précédente de cette même journée affirmait que
régénérer le catalogue déplaçait trois valeurs de récupération, et en faisait un
obstacle à livrer les densités. C'était une erreur de lecture :
`generate_catalog.py` préserve les paramètres calibrés du fichier qu'il lit, et
régénérer sur `HEAD` ne change rien. Les trois valeurs étaient une modification
non commitée déjà dans l'arbre — le seed versionné est simplement en retard sur
la calibration de `generate_seed.py`. Effacées par un `git checkout --`, elles
ont été restaurées en rejouant la calibration, et
`tests/test_seed_catalog_consistency.py` fait désormais échouer ce retard au
lieu de le laisser surprendre le chantier suivant. Détail en D33.

**Substitutions déclarées** (9, règlement `2026-08-20b`) : `riz_basmati` →
aliment 4471 (riz blanc grain long ordinaire, sec), `moutarde_dijon` → 1135
(moutarde brune prête-à-servir, et non la jaune plus sucrée), et les sept formes
de pâtes sèches — fusilli, penne, rotini, linguine, fettuccine, spaghettoni,
orzo — vers l'aliment 4515 « Pâtes (spaghetti, macaroni), enrichi, sec » : la
géométrie ne change ni l'énergie ni les macros.

**Couverture après cette tranche** (`python
scripts/audit_recipe_nutrition_coverage.py`) : 1 recette calculable sur 161,
**508 lignes calculées** (contre 393 au début de la journée), 184 négligeables,
**200 ingrédients bloquants** (contre 215). Les blocages restants : 191 sans
aliment FCÉN, 5 au-delà du plafond négligeable, 4 ambigus — plus aucune densité
ni masse par unité manquante parmi les ingrédients déjà appariés.

**À quelle distance sont les recettes suivantes** (mesuré, `nutrition-coverage`
du 2026-08-20c) : 1 recette à zéro manque, **4 à un seul ingrédient**
(`sucre_blanc`, `levure_alimentaire`, `tomate_conserve`, `lentille_rouge` —
tous quatre proposés par le manifeste), 19 à deux, 28 à trois. Une première
session de revue de cinq ingrédients ferait donc passer la couverture de 1 à 5
recettes, et la vingtaine suivante à une vingtaine de recettes. C'est le chiffre
à suivre, plus parlant que le nombre de bloquants.

**Ce qui reste, et l'ordre n'a pas changé.** Les sessions de revue (le manifeste
est prêt, la file est classée par recettes complétées), puis l'application des
densités une fois le désaccord seed/générateur réconcilié, puis les 10
placeholders `_non_precise` — qui, eux, attendent que leur frère précis soit
apparié (`lait_non_precise` ne peut pointer vers l'aliment de `lait_325` avant
que `lait_325` en ait un). Le ticket qui les décrivait comme débloqués par le
calcul l'était donc à tort : ils dépendent des lots de curation.

**Un mécanisme en moins que prévu** : la fusion des placeholders vers leur
frère n'est plus nécessaire pour la nutrition. Deux ingrédients canoniques
peuvent citer le même aliment FCÉN dans le règlement, là où la contrainte
d'unicité de `canonical_ingredient_external_ref` l'interdisait sur le pont.

### Cinq défauts corrigés en revue (règlement `2026-08-20c`)

Aucun n'était visible en relisant le code; tous sont consignés en test.

1. **La borne ne couvrait que l'énergie.** Une ligne négligeable publiait
   `0,0 g` de lipides comme un fait mesuré, alors que la borne de famille des
   épices (muscade, 41,56 g de lipides/100 g) en omet jusqu'à 1,04 g par
   portion. Le règlement déclare désormais les **quatre** teneurs, la recette
   publie quatre bornes, et l'écran met un « ± » sous chaque nombre. Détail en
   D29 (suite) — c'est la faute que ce module dit précisément ne pas commettre.
2. **66,06 g proposés pour un œuf de 52,61 g** (+26 %) : sept calibres publiés,
   départagés au plus court libellé, et la ligature « œ » non réduite dans ce
   module-ci. La dérivation refuse maintenant et publie les candidats.
3. **Les taux de matière grasse étaient illisibles** : « Crème 35 % » proposait
   « Crème, légère, 5 % M.G. » — 4,6 fois moins d'énergie. Les nombres comptent
   désormais comme des mots. Vérifié après correction : `creme_35` → aliment
   138 (35 % M.G.), `lait_325` → les trois laits à 3,25 % en tête.
4. **Deux éditions d'archive se mélangeaient** (latent aujourd'hui, certain au
   prochain import) : fausses ambiguïtés sur le pont, et teneurs panachées entre
   éditions. Le règlement nomme son édition, le parseur l'exige, la façade s'y
   restreint.
5. **Un test mentait sur l'archive** : l'aliment 61 n'est pas du lait 3,25 %
   mais du 2 %. La fixture masquait le défaut n° 3.

**Après corrections** : 468 tests passent, `tsc -b` propre. La salsa se lit
« 48,6 kcal ± 0,8 — P 1,0 ± 0,1 g — L 3,1 ± 0,1 g — G 5,2 ± 0,3 g ». Couverture
inchangée (1/161 recettes, 486 lignes calculées, 206 bloquants) : ces
corrections rendent les chiffres honnêtes, pas plus nombreux.

## Les épiceries et produits fictifs quittent le seed que la base charge (2026-08-20)

**Signalé.** « Il y a encore des vestiges de produits et épiceries tests. »

**Ce que la base portait, mesuré avant de toucher à quoi que ce soit.** Quatre
épiceries inventées — Maxi-Prix, SuperFrais, Marché Central, L'Épicier du Coin,
toutes à Montréal — avec 83 produits inventés (« Maison Rivard », « Val-Mont »,
« Récolte d'Or »), 564 appariements, 1 128 prix et 2 256 offres en staging, sur
la fenêtre du 20 juillet au 16 août 2026. En face, un seul magasin réel avait
des prix : Super C 640. Le préfiltrage et le solveur ne distinguent pas un prix
capturé d'un prix fabriqué — les deux sont des lignes de `market.price` — donc un
plan daté dans cette fenêtre composait un panier chez une bannière qui n'existe
pas, et l'écran d'épicerie l'affichait comme une course à faire. D24 avait
corrigé la moitié du problème (faire entrer le vrai catalogue) ; le faux était
resté.

**La décision à retenir : déplacer, pas supprimer.** Ces produits et ces prix
portent deux fonctions réelles. `generate_seed.py::ingredients_json` en **dérive**
la périssabilité et σ des 23 ingrédients historiques (D8), et
`tests/test_seed_catalog_consistency.py` verrouille cette dérivation ; trois
tests du solveur y lisent le seul marché non trivial disponible —
`test_min_grocery_spend.py` mesure tout son plancher de dépense dessus. Les
supprimer aurait coûté la calibration de σ et cette couverture pour régler un
problème qui n'est pas leur existence mais leur **destination**. Ils vivent
donc dans `seed/demo`, régénéré **octet pour octet** par le même générateur
(vérifié : σ ne bouge pas d'un chiffre) ; `seed/main` — le seul répertoire que
`app.seeding.seed` charge dans la base — ne garde que `maxi_7552` et
`superc_640`, sans un seul produit ni prix.

**Trois conséquences de code, chacune une petite décision.**
- `products.json` devient **optionnel** au seeding et un `raw_offers.json`
  absent vaut « aucune offre », pas une erreur : semer un répertoire sans
  circulaire JSON n'a rien à faire atterrir, ce n'est pas une panne.
- `tests/seed_loader.py::problem_from_seed_dir` gagne `market_dir` — la
  superposition catalogue réel + marché synthétique est **explicite à l'appel**,
  jamais implicite dans un répertoire. C'est ce qui garde les 468 tests verts
  sans réintroduire le faux marché nulle part.
- `scripts/purge_demo_market.py` retire les lignes déjà chargées, rien sans
  `--apply`, identités lues de `seed/demo` (jamais recopiées), et **refuse**
  d'écrire si les deux marchés se croisent. Vérifié qu'ils ne se croisent pas
  avant de supprimer : 0 produit de démonstration prixé en magasin réel, 0
  produit réel prixé en magasin de démonstration.

**Vérifié en exécutant, contre PostgreSQL réel** : purge appliquée —
`market.store` 6 → 2, `market.product` 2 280 → 2 197, `market.product_mapping`
2 761 → 2 197, `market.price` 5 240 → 4 112, `staging.raw_offer` 6 368 → 4 112,
soit exactement ce que `seed/demo` déclare et rien d'autre ; rejeu du script :
« rien à retirer » ; `python -m app.seeding.seed --seed-dir ../seed/main`
rapporte désormais « market.store : 2 lignes, market.product : 0 lignes, 0
nouvelles offres » ; `check_profile_drift` propre. **468 tests passés, 0 échec,
0 sauté.** Détail et rationnel : `docs/deviations.md`, D34.

**Nommé, pas corrigé — l'adresse du ménage.** `home_lat/home_lng` place le
domicile à Montréal alors que les deux bannières réelles sont à Québec, à
~225 km. C'est un vestige de la même famille, mais l'adresse réelle du ménage
n'est pas une valeur qu'un correctif peut inventer : elle se saisit dans Ménage ›
Préférences. D26 empêche déjà l'effet le plus grave (un magasin sans prix ne peut
plus être retenu parce qu'il est proche) ; le terme de déplacement, lui, reste
calculé sur une distance fausse tant que l'adresse n'est pas corrigée.
`maxi_7552` reste en base sans aucun prix — c'est un magasin réel dont la
capture ne produit encore que des titres indexés, pas une bannière fantôme.

## Les recettes inventées quittent le seed que la base charge (2026-08-21)

**Le pendant exact de D34, côté catalogue.** `seed/main` livrait 40 recettes
écrites à la main — vingt bases (« Chili aux lentilles », « Galettes de
lentilles », « Saag au tofu », « Pâté chinois revisité »…) et vingt
déclinaisons `_familial` dérivées par formule. Aucune source : ni URL, ni
livre, ni `import_origin` ; le plat, les portions et les quantités ont été
posés pour donner au solveur de quoi arbitrer. Le solveur ne distingue pas une
recette importée d'une recette fabriquée — les deux sont des lignes de
`catalog.recipe` — donc le produit proposait à un vrai ménage de cuisiner des
plats qui n'existent nulle part. Ce n'était pas théorique : D24 mesurait déjà
un menu « chili aux lentilles, galettes de lentilles, riz frit et sauté de
tofu, à 1,00 $/portion ».

**Déplacer, pas supprimer — pour la même raison qu'en D34.** Mesuré : les 23
ingrédients du marché synthétique de `seed/demo` couvrent **40 des 40**
recettes de démonstration et **1 des 121** recettes importées. Les supprimer
aurait coûté aux tests du solveur le seul marché non trivial dont ils
disposent. Elles vivent donc dans `seed/demo/recipes.json` (`DEMO_RECIPES`,
ex-`ALL_RECIPES`), et `seed_loader.py::problem_from_seed_dir` **concatène** les
recettes des deux répertoires quand `market_dir` en porte : les tests voient
toujours les 161, `seed/main` n'en livre plus que 121, toutes importées.

**Le script de purge emporte les plans, et le dit.** `household.plan` cite ses
recettes en JSONB sans clé étrangère — rien ne part en cascade — et
`planning.py::_plan_view` fait `recipes[rid]` sans garde. Retirer les recettes
sans retirer ces plans échangerait un faux menu contre une 500.
`scripts/purge_demo_recipes.py` liste donc les plans touchés et **refuse**
d'écrire tant que `--drop-committed` ne tranche pas le sort des `committed`.

**Ce que le déplacement a mis à nu, mesuré.** Le préfiltrage écarte une recette
sans composante marginale quand `enable_batch_fixed_cost` est éteint (D25), et
les 121 recettes importées sont toutes dans ce cas. Sur `seed/main` seul, au
20 août 2026 : drapeau à `False` (le défaut de `SolverConfig`) → **0 recette
survivante** ; à `True` → 81. Les 40 recettes inventées étaient donc ce qui
masquait le fait que la configuration par défaut ne sait rien faire du corpus
réel. Le basculement du défaut n'est **pas** fait ici : il change l'équation de
besoin de toutes les recettes et mérite son propre écart, mesuré.

**Vérifié en exécutant, contre PostgreSQL réel** : `generate_seed.py` rejoué —
`seed/main` 121 recettes importées, `seed/demo` 40 recettes écrites à la main,
catalogue et marché inchangés octet pour octet ; `purge_demo_recipes.py` a
d'abord **refusé** (5 plans `committed`), puis appliqué avec
`--drop-committed` — `catalog.recipe` 161 → 121, `catalog.recipe_ingredient`
1 441 → 1 223, `household.plan` 108 → 14 (89 `proposed` + 5 `committed`
retirés) ; rejeu : « rien à retirer » ; `python -m app.seeding.seed --seed-dir
../seed/main` rapporte désormais « catalog.recipe : 121 lignes ».
**469 tests passés, 0 échec, 0 sauté** — un de plus qu'en D34, le nouveau
script étant balayé par le test paramétré de `test_weekly_runner_wiring.py`. Détail et rationnel :
`docs/deviations.md`, D35.


## Curation nutritionnelle — 113 recettes calculables sur 121 (2026-08-21)

Suite directe de D29–D33. Le calcul nutritionnel était livré et **1 recette sur
121** sortait un chiffre : ce qui manquait n'était pas du code mais des
décisions d'appariement. Cette session en a écrit 193, et la couverture passe à
**113/121** (1 058 lignes calculées, 8 ingrédients encore bloquants). Détail et
rationnel : `docs/deviations.md`, D36 (les décisions) et D37 (les formes que le
fichier fédéral publie autrement, et trois quantités d'import fausses).

**Le mécanisme qui manquait.** 189 des 198 bloquants portaient `no_cnf_food` —
aucun aliment fédéral rattaché — et aucun des trois titres de D30 ne décrivait
ce cas. Quatrième titre : `attachment` (la curation d'identité n'a rien
rattaché, le FCÉN publie l'aliment). Refusé si l'ingrédient porte déjà un
aliment (`chosen_food_already_attached`), sinon il devenait le titre
fourre-tout.

```
services/food_choice_ledger.py       rend les entrées du règlement — pur
scripts/declare_food_choices.py      commande : décisions -> règlement, versionné
tests/test_food_choice_ledger.py     7 tests
tests/test_nutrition_coverage_pin.py plancher 105/121 + toute raison de trou nommée
```

**La provenance est rendue, jamais saisie.** `render_food_choices` transcrit les
quatre teneurs publiées depuis l'archive et refuse un aliment introuvable, une
justification vide, un `attachment` sur un ingrédient déjà rattaché, un
`primary` hors des aliments portés. C'est la réponse au défaut que la session
précédente a trouvé chez elle : quatre provenances de densité rétro-calculées au
lieu d'être transcrites.

**Où vivent les décisions** — `config/nutrition-rules.json` (205 choix
d'aliment, `rule_version` 2026-08-21d), `config/cook_recipe_curation.json`
(12 masses par unité vérifiées), `seed/main/canonical_ingredients.json`
(46 densités, dont 40 dérivées du FCÉN). Rien n'a été ajouté à
`seed/main/cnf_catalog_curation.json` : ce fichier est régénéré en entier par
`refine_cnf_catalog.py`, une décision écrite à la main y serait effacée.

**Ce qui reste bloquant est un trou du fichier fédéral**, pas de la curation :
aucun aliment publié (pâte brisée, cari vert, gnocchis, gomme de xanthane,
origan frais), aucune mesure de volume ou de compte (cognac, confiture, pain
pita, pain à sous-marin, feuille de riz…), ou des mesures qui ne s'accordent pas
(lait de coco en conserve). Le calibre d'un œuf, d'une tortilla ou d'un carré de
wonton reste **un jugement écrit à la main**, avec les calibres écartés : la
dérivation refuse, et c'est voulu — elle propose 35 g (« 1 tranche » de pain
italien) pour un pain à sous-marin entier.

**Ce que D37 a ajouté.** Trois lectures que la dérivation ne faisait pas : un
compte fractionnaire (« 1/2 pita = 30 g » → 60 g l'unité), la cuillère fédérale
comme volume (table 15 ml, thé 5 ml — la seule mesure de certaines poudres), et
l'accord des ratios jugé sur les volumes d'au moins 50 ml (« 15 ml = 15,203 g »
est une cuillère à table écrite en millilitres, et faisait refuser une densité
que trois grands volumes donnent à l'identique). Plus une déclaration d'apport
négligeable pour l'origan frais, bornée par la teneur du séché — qui majore.

**Trois quantités d'import fausses, révélées par le déblocage** : `pain_levain`
2 200 g → 384 g, `pate_wonton` 454 unités → 57, `roquette` 2 000 g → 169 g. Un
ingrédient bloquant ne publie pas de total : c'est le déblocage qui a rendu ces
erreurs visibles. Corrigées par `quantity_overrides`, qui gagnent désormais
**toujours** — ils n'étaient consultés que si la projection amont était
incomplète, donc jamais pour un canonique qui se compte à l'unité.

**Ce qui reste, et pourquoi.** Huit bloquants : trois sans aliment publié (pâte
brisée, cari vert, gnocchis), deux sans mesure de compte (feuille de riz, pain à
sous-marin), trois dont la seule mesure de volume décrit un solide en dés
(feuillage de fenouil, aubergine grillée, jus de cornichon) — ceux-là demandent
une **masse par volume tassé**, distincte d'une densité, et leur canon devrait
se mesurer en grammes. Par ailleurs 19 recettes dépassent 900 kcal/portion, et
le premier cas n'est pas une erreur de donnée : 750 ml d'huile de friture
comptés comme consommés. Quantité achetée contre quantité consommée : le contrat
de recette ne les distingue pas.
