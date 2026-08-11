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
