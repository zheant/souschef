# Roadmap — prix fiable pour chaque recette

Statut de départ : 2026-08-13.

## Avancement vérifié — 2026-08-13, deuxième passe

| Mesure | Départ | Première passe | Maintenant |
|---|---:|---:|---:|
| Recettes avec devis complet | 28/161 | 64/161 | **129/161** |
| Ingrédients distincts avec prix exploitable | 186/308 | 234/308 | **281/308** |
| Ingrédients sans produit approuvé | 87 | 54 | **25** |
| Lacunes de format ou d'unité | 35 | 20 | **2** |

Commande unique, reproductible, sans PostgreSQL :

```bash
python scripts/audit_recipe_pricing_coverage.py --week 2026-W33 \
  --superc-root data/catalogue-captures/superc/2026-W33 \
  --json-output data/catalogue-reports/recipe-pricing-coverage-2026-W33.json \
  --minimum-complete-recipes 129
```

Le seuil de non-régression n'est pas encore câblé dans la collecte
hebdomadaire : il faut le passer à la main, sinon une baisse de couverture
passe inaperçue.

### Ce qui a débloqué les 65 recettes supplémentaires

Quatre causes distinctes, toutes mesurées avant correction :

1. **La chaîne de mesure ignorait les captures les plus riches.** Les deux
   scripts avaient chacun leur copie de la découverte des dossiers de capture,
   divergentes : celle de l'audit excluait explicitement les dossiers
   `run-*`, celle des devis les incluait comme dossiers vides. Les exécutions
   isolées — plus récentes, seules à porter `sale_mode`, le prix unitaire et
   `unit_details_text` — n'entraient donc jamais dans la mesure. Remplacé par
   `app/ingestion/capture_layout.py`, partagé et testé.
2. **Un format publié n'était pas lu.** Super C vend l'oignon vert « 1 botte »,
   le céleri « Vendu individuellement » : aucune masse, mais un prix unitaire
   « 1,99 $ / 1 un » égal au prix affiché. C'est un format publié, pas une
   estimation; `_sold_as_single_unit` le lit, à la condition stricte que les
   deux prix coïncident — une référence « / 100 g » reste un prix de
   comparaison et ne devient jamais un emballage. De même, « 6 x 116 g »
   publie un compte de six articles.
3. **Des rayons entiers n'étaient pas configurés.** Ajoutés à
   `config/catalogues.json` puis collectés : céréales-tartinades-et-sirops,
   condiments-et-garnitures, gastronomie-internationale, cuisine-du-monde,
   collations sucrées, et le rayon surgelés complet. 2 249 produits de plus,
   qui apportent le sirop d'érable, la mélasse, la moutarde à l'ancienne, la
   sauce de poisson, la pâte phyllo.
4. **Des faux rejets et des faux appariements.** Le mélange tex-mex, les
   gnocchis, la pancetta, les raviolis au fromage, l'assaisonnement italiano
   et le babeurre de culture étaient rejetés alors qu'ils sont exactement
   l'ingrédient demandé. À l'inverse, « Tomates en dés avec épices
   italiennes » était rattaché aux épices italiennes plutôt qu'aux tomates en
   conserve, et un **détergent à lessive était approuvé comme « eau »**.

### Ce qui bloque encore, et pourquoi

Les 32 recettes incomplètes le sont chacune pour un ou deux ingrédients, et
la cause est presque toujours la même : **Super C ne vend pas le produit**
dans les rayons collectés. Boulettes de veau préparées (4 recettes), pâte
miso, lard salé, saucisse de Toulouse de porc, gomme de xanthane, cognac,
pâte de cari vert thaï, bouillon de champignons, pâte à wonton, pâte brisée.
Aucune conversion ne corrige une absence; il faudra soit une autre bannière,
soit une décision de substitution assumée recette par recette.

Trois cas restent des lacunes de données, pas d'inventaire : le feuillage de
fenouil et le jus de cornichon sont de vrais dérivés (du bulbe, du pot de
cornichons) mais aucune source ne publie la quantité obtenue; la demi-caisse
de figues fraîches n'a aucune masse publiée.

### Conversions : ce qui est sourcé et ce qui ne l'est pas

`config/ingredient-procurement-rules.json` porte 31 conversions, chacune avec
sa provenance et son niveau de confiance. **Quinze sont sourcées au Fichier
canadien sur les éléments nutritifs 2026** (tranche de pain 36 g, tête de
laitue iceberg 539 g, bulbe de fenouil 234 g, câpres, cornichons à l'aneth,
châtaignes d'eau, maïs en conserve…).

**Onze sont déclarées `estimated`** et ne doivent jamais être présentées
comme exactes. Elles se répartissent en deux familles :

- *un compte non publié* — botte d'oignons verts (7 tiges), pied de céleri
  (10 tiges), botte de persil (60 brins), botte de chou frisé, feuille de
  laurier (0,2 g), bâton de cannelle (2,5 g), pain pita. Le FCÉN donne le
  poids d'une tige ou d'une feuille, jamais le contenu d'une botte
  commerciale;
- *une densité non publiée* — mélasse, olives, crème glacée, soupe condensée,
  lentilles en conserve (densité transposée des pois chiches).

Toutes portent dans leur provenance la mention « à remplacer par une pesée ».
Une seule pesée par ingrédient les ferait passer à `audited_conversion`, et
c'est le geste le plus rentable qui reste : elles touchent 86 des 129 devis.

- P0 est terminé : audit déterministe, rapport JSON et seuil de non-régression.
- P1 est terminé pour Super C : 78/78 pages de rabais, 2 599 produits vus
  sur la page officielle et 2 537 observations promotionnelles; les rayons
  complémentaires ont aussi été capturés. Maxi est encore en cours : son run
  a été correctement rejeté après une vérification humaine non complétée et
  une réponse HTTP 403.
- P2 à P4 sont en cours : curation revue, produits au poids, formats à plusieurs
  dimensions, six conversions de conserves et deux conversions additionnelles
  sourcées dans le Fichier canadien sur les éléments nutritifs 2026, eau et
  jaune d'œuf dérivé.
- P5 et P6 sont implémentés : module pur de devis, API, affichage front-end et
  niveaux de confiance.

Rapports reproductibles :

- `data/catalogue-reports/recipe-pricing-coverage-final-combined-2026-W33.json`
- `data/catalogue-reports/recipe-quotes-final-combined-2026-W33.json`

*(Ce paragraphe décrivait les blocages de la première passe — oignon vert,
laurier, céleri, persil, sirop d'érable, vin sec, moutarde à l'ancienne, jus
de lime. Tous sont résolus; voir « Ce qui bloque encore » ci-dessus.)*

## Objectif

Fournir un devis explicable pour chacune des 161 recettes, avec des prix de la
semaine courante chez Maxi et Super C, sans inventer de format, de densité ou
d'équivalence culinaire.

Une recette est considérée comme couverte lorsque chacun de ses ingrédients a
une résolution d'approvisionnement auditée : produit acheté directement,
ingrédient dérivé d'un produit acheté, essentiel sans achat, ou exclusion
explicitement justifiée. Un ingrédient silencieusement ignoré ne compte jamais
comme couvert.

## Définition du prix

Le terme « prix d'une recette » doit être séparé en trois montants :

1. **Coût consommé** — valeur des quantités réellement utilisées.
2. **Décaissement autonome** — coût des emballages qu'il faut acheter pour
   préparer la recette depuis un garde-manger vide.
3. **Coût marginal au menu** — achat supplémentaire causé par l'ajout de la
   recette à un menu qui partage déjà des produits et du stock.

L'interface par défaut affichera le coût consommé total et par portion. Le
décaissement autonome sera affiché séparément. Le coût marginal restera dans
la planification de menu, car il dépend des autres recettes et du garde-manger.

Chaque montant portera également un niveau de confiance :

- `exact` : format et conversion fournis par le détaillant;
- `audited_conversion` : conversion documentée et approuvée;
- `estimated` : estimation déclarée, jamais présentée comme exacte;
- `incomplete` : au moins une donnée indispensable manque.

Cette sémantique devra être enregistrée dans un ADR avant de figer le contrat
de l'API.

## Point de départ mesuré

| Mesure | Valeur actuelle |
|---|---:|
| Recettes | 161 |
| Ingrédients distincts utilisés | 308 |
| Ingrédients avec un prix Super C exploitable | 186 |
| Lacunes de format ou d'unité | 35 |
| Lacunes d'identité ou de périmètre | 87 |
| Recettes entièrement chiffrables | 28 |

Une recette contient en moyenne 8,95 ingrédients distincts et il en manque
2,34 en moyenne. Vingt-sept recettes ne sont bloquées que par un seul
ingrédient; elles constituent le premier front de travail.

## Architecture cible

```text
Pages détaillants
    → capture brute avec preuve de prix et de quantité
    → curation produit commercial → ingrédient achetable
    → règles d'approvisionnement et de conversion
    → RecipeCostingModule
    → API et interface utilisateur
```

Le nouveau `RecipeCostingModule` sera le module profond du calcul. Son
interface recevra les recettes, les portions, la date, les magasins admissibles
et le garde-manger éventuel; elle retournera des devis et leurs preuves. Les
scrapers ne calculeront jamais un coût de recette et l'API ne reconstruira pas
les calculs elle-même.

## Phase 0 — Verrouiller la mesure

### Travaux

- Ajouter une commande déterministe d'audit de couverture.
- Produire les résultats en JSON et en texte : couverture par ingrédient,
  recette, magasin et cause de blocage.
- Conserver un petit jeu de recettes témoins couvrant format fixe, produit au
  poids, conserve en volume, ingrédient à l'unité et ingrédient dérivé.
- Ajouter une garde empêchant une baisse silencieuse de couverture.

### Critère de sortie

La commande reproduit le point de départ et attribue chaque ingrédient manquant
à une cause unique. Elle s'exécute sans PostgreSQL afin de rester rapide et
déterministe.

## Phase 1 — Produire des captures hebdomadaires fiables

### Travaux

- Exécuter une collecte complète Maxi et Super C incluant les pages de rabais.
- Corriger la collecte Maxi jusqu'à obtenir un véritable catalogue, plutôt
  qu'un produit répété entre plusieurs rayons.
- Conserver dans la capture brute : prix affiché, prix régulier, prix réduit,
  prix unitaire (`$/kg`, `$/100 g`, etc.), unité de référence, format affiché,
  mode de vente fixe/au poids, magasin, URL et période de validité.
- Lors de la déduplication, conserver l'observation la plus riche et la preuve
  promotionnelle; ne pas sélectionner simplement la dernière ligne.
- Ajouter des seuils d'anomalie comparés à la semaine précédente : produits
  distincts, pages, catégories et promotions. Une chute importante rend la
  capture incomplète.

### Critère de sortie

Les deux rapports indiquent `weekly_deals_scanned: true`, au moins une
promotion, un nombre plausible de produits distincts et la semaine
jeudi-mercredi correcte. Les anciennes captures sans rabais restent
inutilisables comme exécution complète.

## Phase 2 — Réaligner la curation sur les recettes réelles

La politique de curation actuelle a été conçue pour le petit catalogue de
démonstration. Elle exclut notamment des catégories qui contiennent maintenant
des ingrédients demandés par les recettes importées : pains, tortillas,
saucisses, charcuteries, sauces et marinades.

### Travaux

- Générer la liste priorisée des identités requises par les 161 recettes.
- Scanner les rayons manquants nécessaires à ces identités.
- Remplacer les exclusions globales de catégories par des décisions sur
  l'identité du produit lorsque la catégorie peut contenir un ingrédient utile.
- Corriger en priorité les faux rejets, par exemple la sauce Worcestershire.
- Réviser les 27 recettes qui n'ont qu'un ingrédient manquant, puis classer les
  travaux suivants selon le nombre de recettes débloquées.
- Continuer d'exclure les produits composés qui ne correspondent pas réellement
  à l'ingrédient demandé; être présent dans une recette ne suffit pas à rendre
  un rapprochement valide.

### Critère de sortie

Chaque ingrédient directement achetable possède au moins un produit approuvé
dans un des deux magasins, ou une décision explicite indiquant qu'il doit être
traité comme dérivé ou essentiel.

## Phase 3 — Modéliser les quantités achetables

Cette phase traite les 35 lacunes déjà reliées à un produit, mais inutilisables
à cause de leur format.

### 3A — Produits vendus au poids

- Ajouter un mode de vente `fixed_package` ou `variable_weight`.
- Pour un produit au poids, stocker le prix par unité de référence et
  l'incrément d'achat, plutôt que de fabriquer un emballage fictif.
- Adapter les variables d'achat du solveur : entières pour les emballages,
  compatibles avec l'incrément autorisé pour le poids variable.
- Couvrir en premier le bœuf haché, le porc haché, les coupes de viande et les
  légumes vendus au poids.

### 3B — Masse, volume et unité

- Utiliser la densité uniquement pour une conversion masse-volume documentée;
  ne jamais appliquer implicitement `1 ml = 1 g`.
- Ajouter les densités auditées nécessaires aux tomates, pâtes de tomate,
  légumineuses en conserve et autres produits prioritaires.
- Modéliser séparément les conversions unité-masse avec un poids ou rendement
  par unité sourcé : céleri, oignon vert, feuilles de laurier, etc.
- Conserver la provenance, la date et le niveau de confiance de chaque
  conversion.

### Critère de sortie

Chaque produit approuvé peut produire un prix par unité de consommation, ou
reste explicitement `incomplete`. Sur le jeu de données actuel, résoudre les
seules lacunes de format doit faire passer la couverture d'au moins 28 à 53
recettes; la nouvelle collecte établira ensuite la cible révisée.

## Phase 4 — Relier consommation et approvisionnement

Un ingrédient de recette n'est pas toujours une identité d'achat indépendante.
Par exemple, le jus et le zeste peuvent provenir d'un citron, et le jaune d'œuf
d'un œuf entier.

### Travaux

- Fusionner les identités qui représentent réellement le même achat, par
  exemple `epinard_frais` et l'identité commerciale appropriée, après revue.
- Ajouter des règles d'approvisionnement auditables pour les vrais dérivés :
  jus de citron/lime, zeste, jaune d'œuf, jus de cornichon et feuillage de
  fenouil.
- Agréger les besoins partageant le même produit parent avant d'arrondir les
  emballages; une recette utilisant jus et zeste ne doit pas acheter deux lots
  de citrons indépendants.
- Définir explicitement les essentiels sans achat, notamment l'eau, et leur
  effet sur le coût consommé et le décaissement.
- Ne pas utiliser la famille d'ingrédients comme substitut automatique : une
  famille est descriptive et ne prouve pas l'interchangeabilité.

### Critère de sortie

Les 308 ingrédients utilisés ont tous une résolution d'approvisionnement
explicite. Aucune recette n'est rendue complète en ignorant silencieusement un
ingrédient.

## Phase 5 — Construire le calcul de prix des recettes

### Interface proposée

```python
RecipeCostingModule.quote_all(
    recipes,
    prices,
    servings,
    stores,
    pantry=None,
) -> list[RecipeQuote]
```

`RecipeQuote` contiendra au minimum :

- coût consommé total et par portion;
- décaissement autonome total;
- prix régulier comparable et économies promotionnelles;
- magasin ou combinaison de magasins;
- emballages retenus et surplus;
- période de validité;
- niveau de confiance;
- ingrédients et raisons lorsque le devis est incomplet.

### Travaux

- Implémenter le calcul comme une fonction pure derrière cette interface.
- Réutiliser les prix courants validés et les règles d'arrondissement des
  emballages; ne pas dupliquer ces règles dans l'API ou le front-end.
- Définir si le « meilleur prix » autorise plusieurs magasins et comment le
  déplacement est présenté. Par défaut, fournir aussi un devis par magasin.
- Ajouter des tests manuels de référence avec calcul papier pour chaque mode de
  vente et chaque type de conversion.

### Critère de sortie

Les 161 recettes retournent soit un devis complet, soit un statut incomplet
avec une cause structurée. L'objectif final est 161 devis complets sans
estimation cachée.

## Phase 6 — Exposer, surveiller et maintenir

### Travaux

- Ajouter un endpoint de lecture des devis sans accès SQL direct depuis la
  route; la route appelle le module.
- Afficher sur les cartes recette : coût par portion, coût total, décaissement,
  économies et semaine de validité.
- Montrer clairement `exact`, `audited_conversion` ou `estimated`.
- Publier un rapport hebdomadaire de couverture après chaque collecte.
- Bloquer la publication d'une semaine si les rabais n'ont pas été scannés ou
  si la couverture chute au-delà du seuil accepté.

### Critère de sortie

Un utilisateur peut expliquer chaque prix en remontant de la recette aux
quantités, conversions, produits, magasins et observations de prix de la
semaine.

## Ordre de livraison recommandé

```text
P0 mesure
  → P1 collecte fiable
    → P2 curation complète
      → P3 quantités achetables
        → P4 approvisionnement dérivé
          → P5 calcul
            → P6 interface et surveillance
```

P2 et P3 peuvent avancer en parallèle après la première nouvelle capture, mais
P5 ne doit pas figer son interface avant les décisions de P3 et P4.

## Interdictions de qualité

- Aucun défaut silencieux `1 ml = 1 g`.
- Aucun poids moyen sans source et niveau de confiance.
- Aucun ingrédient manquant compté comme coût nul, sauf politique explicite
  d'essentiel sans achat.
- Aucun prix promotionnel utilisé hors de sa période.
- Aucune équivalence culinaire déduite seulement de la famille d'ingrédients.
- Aucun total présenté comme exact lorsqu'une conversion est estimée.

## Passe de correction — 2026-08-13

Déclenchée par une revue de l'artefact publié
([`revue-qualite-devis-2026-W33.md`](revue-qualite-devis-2026-W33.md), 10
problèmes mesurés). Ce que la mesure de couverture ne voyait pas : un devis
peut être complet, arithmétiquement juste, et faux.

| Mesure | Avant | Après |
|---|---:|---:|
| Devis complets | 129/161 | **130/161** |
| Ingrédients chiffrables | 280/308 | **282/309** |
| **Devis sans réserve de recette** | non mesuré | **130/161** |
| Lignes comptant des articles chiffrées au gramme | 166 | **0** |
| Recettes dont une quantité était écrasée en base | 28 | **0** |
| Produits composés tenant lieu d'ingrédient de base | 125 | **0** |
| Coût de l'ail sur l'ensemble des devis | 59,20 $ | 7,40 $ |
| Décaissement cumulé des 129 devis | 6 346,76 $ | 4 333,61 $ |
| Ratio médian acheté / requis | 7,3× | 3,0× |

Six nouveaux garde-fous, tous exécutables sans PostgreSQL :

1. `services/recipe_quality.py` — un devis complet n'est plus présenté comme
   fiable si la recette elle-même demande 1 g d'aubergine, compte un
   ingrédient deux fois ou déclare 625 portions. Le compte
   `reliable_recipes` figure dans le rapport.
2. `recipe_costing.py` sépare la valorisation (meilleur prix unitaire) de
   l'achat (panier le moins cher). Le décaissement cesse d'être le prix du
   plus gros format du magasin.
3. `config/quebec-tax-rates.json` — le taux de taxe n'est plus un zéro
   implicite pour tout le catalogue.
4. `import_cook_recipes.py` ne reprend plus telle quelle une quantité
   projetée quand la ligne source comptait des articles : « 1 aubergine »
   ne peut plus devenir 1 g. 47 équivalences ajoutées, 30 vérifiées au
   FCÉN 2026, 17 estimées avec leur raison. 157 lignes requantifiées dans
   86 recettes, 215,92 $ de coût consommé qui manquait.
5. Le même import additionne les lignes d'un ingrédient répété. La
   contrainte d'unicité de `recipe_ingredient` faisait qu'en base la
   dernière ligne **écrasait** les autres (405 g de fécule ramenés à
   62,5 g) alors que le calcul sur le JSON les additionnait : deux
   réponses pour une recette selon le chemin.
6. `IdentityRules` refuse qu'un produit composé tienne lieu d'ingrédient
   de base, sauf si le marqueur appartient à l'identité du canonique.
   125 produits écartés, aucune perte de couverture.

Commande de rendu de la page, à la suite de la commande de mesure :

```bash
python scripts/build_quote_artifact.py \
  --report data/catalogue-reports/recipe-quotes-2026-W33.json \
  --period "semaine du 13 au 19 août 2026" \
  --output data/catalogue-reports/devis-2026-W33.html
```

### Interdictions ajoutées

- Aucun cumul d'un montant défini sur un panier autonome : les devis
  partagent leurs emballages, leur somme ne décrit aucun achat réel.
- Aucun total d'emballage affiché pour un produit vendu au poids.
- Aucun décaissement calculé sur un format que personne n'achèterait pour
  la quantité demandée.
- Aucun rendement publié en pièces ou en volume compté comme un nombre de
  portions.
- Aucun ingrédient présent deux fois dans une recette : la contrainte
  d'unicité en base en perdrait une.
- Aucun produit composé retenu comme ingrédient de base, quel que soit son
  prix au 100 g.
- Aucune équivalence pièce → masse écrite deux fois : la conversion du
  besoin de recette et celle du format de produit lisent la même valeur.
