# Diagnostic architectural et plan de refactorisation

## Résumé

Le principal problème architectural se trouve dans la couche FastAPI, qui
concentre trop de responsabilités et contourne les modules métier. Le solveur,
les ports d'acquisition et le snapshot `ProblemData` sont, en revanche,
correctement placés derrière des interfaces utiles.

L'objectif du refactor est de rendre les routes strictement responsables du
transport HTTP et de concentrer les cas d'usage dans des modules applicatifs
profonds : beaucoup de comportement derrière une interface réduite.

## Diagnostic

### `api/routes.py` mélange plusieurs responsabilités

Le module combine actuellement :

- transport HTTP;
- requêtes SQLAlchemy;
- mutations de données;
- calcul de demande;
- transformation ORM vers réponse;
- calcul du coût attribué;
- accès direct à `staging`;
- traduction des erreurs métier.

Son affirmation « aucune logique métier ici » ne correspond donc pas à son
implémentation. L'accès direct à `staging` contredit également la règle selon
laquelle l'ingestion s'exécute en lot, hors du chemin des requêtes HTTP.

### `services/plan_service.py` va dans la bonne direction

Ce module concentre déjà la génération, la persistance, la construction de la
liste d'épicerie et le commit d'un plan. Il possède donc une profondeur
potentielle importante.

Son interface expose toutefois encore :

- une `Session` SQLAlchemy;
- des modèles ORM comme `Plan`;
- plusieurs dictionnaires non typés;
- un résultat `(Plan, SolveResult)` qui oblige l'appelant à comprendre
  l'implémentation.

Le module contient du comportement utile, mais son interface n'en cache pas
encore suffisamment la complexité.

### Le solveur est déjà un module profond

L'interface `MenuSolver` est petite :

```python
solve(problem, prefiltered, config) -> SolveResult
```

Elle cache la validation, la construction du MILP, les variables, les
contraintes, le calcul des coûts et le diagnostic. Les adapters PuLP et faux
de test démontrent que le seam est réel.

Cette forme doit être conservée.

### `ProblemData` forme une bonne séparation

Le snapshot transforme les modèles PostgreSQL en données métier immuables. Le
solveur ne connaît ni SQLAlchemy ni la connexion à la base.

Le chargeur pourra être déplacé lors du refactor, mais son principe reste
valide.

### La résolution des offres demeure un problème ouvert

`normalize_offers` résout actuellement les offres à partir de
`product_external_key` et ne réutilise pas les mappings manuellement
confirmés pour les offres suivantes. En parallèle, l'endpoint HTTP de mapping
modifie directement des lignes de `staging.raw_offer`.

Il ne suffit pas de déplacer ce code. Le chemin
`raw_text -> product -> ingrédient canonique` doit être conçu avant de figer
une nouvelle interface. Un produit précis doit porter sa marque et son format;
un ingrédient canonique seul ne suffit pas au solveur.

## Architecture cible

```text
Routes FastAPI
   | validation HTTP et codes de réponse seulement
   v
Modules applicatifs
   |-- PlanningModule
   |-- HouseholdModule
   |-- CatalogModule
   `-- OfferResolutionModule
           |
           v
     SQLAlchemy/PostgreSQL
           |
           |-- ProblemData
           v
      MenuSolver interface
           |
           |-- adapter PuLP
           `-- adapter de test
```

Les modules applicatifs cachent la transaction, les requêtes SQLAlchemy, les
modèles ORM et les transformations de sortie. Les routes ne manipulent plus
qu'une interface applicative et des schémas HTTP.

## Modules proposés

### `PlanningModule`

Interface proposée :

```python
generate_plan(profile_id, on_date, config) -> PlanView
get_plan(profile_id, plan_id) -> PlanView
commit_plan(profile_id, plan_id) -> CommitResult
```

L'implémentation cache :

- le chargement de `ProblemData`;
- le scoring et le préfiltrage;
- l'appel du solveur;
- le calcul des besoins;
- la persistance;
- la construction du menu;
- la liste d'épicerie;
- la vérification de propriété du plan;
- la gestion du commit.

Les routes ne reçoivent plus de `Session` et ne manipulent plus de modèle
`Plan`.

### `HouseholdModule`

Interface proposée :

```python
get_profile(profile_id) -> HouseholdView
update_profile(profile_id, changes) -> HouseholdView
get_pantry(profile_id) -> PantryView
update_pantry(profile_id, changes) -> PantryView
```

Le calcul de la demande, la validation des ingrédients et les conversions ORM
restent dans l'implémentation.

### `CatalogModule`

Interface proposée :

```python
search_recipes(query) -> RecipePage
list_stores() -> tuple[StoreView, ...]
```

Ce module cache la pagination, les filtres PostgreSQL et les structures ORM.

### `OfferResolutionModule`

Interface future :

```python
list_unresolved() -> tuple[UnresolvedOffer, ...]
confirm_resolution(command) -> ResolutionResult
```

Sa conception doit attendre la résolution de D15. Une confirmation doit
identifier ou créer un produit précis, pas seulement sélectionner un
ingrédient canonique.

## Approches à éviter

- Ne pas créer une interface repository pour chaque table.
- Ne pas déplacer chaque requête SQL dans un fichier séparé sans déplacer le
  comportement associé.
- Ne pas conserver `Session` dans les interfaces applicatives.
- Ne pas ajouter de ports hypothétiques qui ne possèdent qu'un seul adapter.
- Ne pas refactoriser le solveur pendant ce chantier.
- Ne pas cacher D15 derrière un simple `ProductMappingRepository`.

Ces approches multiplieraient les couches sans augmenter la profondeur des
modules ni la locality des changements.

## Ordre recommandé

1. Ajouter ou confirmer les tests de caractérisation HTTP des comportements
   actuels.
2. Créer des DTO applicatifs typés, indépendants de FastAPI et SQLAlchemy.
3. Extraire `PlanningModule`.
4. Rendre les routes de plans purement HTTP.
5. Extraire `HouseholdModule`.
6. Extraire `CatalogModule`.
7. Vérifier que `routes.py` n'importe plus SQLAlchemy ni `models`.
8. Résoudre explicitement la conception D15.
9. Extraire ensuite `OfferResolutionModule`.
10. Corriger la documentation architecturale lorsque le code respecte
    réellement la règle annoncée.

`PlanningModule` constitue le meilleur premier chantier : il offre le plus
grand gain de locality avec un risque maîtrisable.

## Stratégie de tests

- Conserver les tests HTTP comme contrats externes.
- Tester chaque module applicatif directement à travers son interface contre
  PostgreSQL réel.
- Conserver les tests purs du solveur, du scoring et des conversions.
- Utiliser le faux `MenuSolver` à travers `PlanningModule`.
- Éviter les mocks de repositories SQLAlchemy.
- Tester les résultats observables à travers les interfaces, pas l'état
  interne des modules.
- Une fois les nouveaux tests en place, retirer ceux qui inspectent des
  détails internes devenus inaccessibles.

Cette stratégie suit le principe « remplacer, ne pas superposer » : les tests
des anciens modules superficiels ne doivent pas survivre uniquement parce
qu'ils existaient avant le refactor.
