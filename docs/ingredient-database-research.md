# Recherche d'un référentiel public d'ingrédients de recettes

Date de vérification : 12 août 2026

## Réponse courte

Il n'existe pas de base publique qui soit directement un répertoire prêt à l'emploi des « ingrédients achetables en épicerie et utilisés dans les recettes, à l'exclusion des collations et autres produits hors recette ».

La meilleure base de départ pour Souschef/Cook est le **Fichier canadien sur les éléments nutritifs (FCÉN/CNF) 2026** de Santé Canada : il est canadien, bilingue ligne par ligne, possède des codes et couvre 5 993 aliments. Il faut toutefois le filtrer et le transformer, car il comprend aussi des plats préparés, boissons, sucreries, aliments pour bébés, repas-minute et collations. Il décrit des aliments nutritionnels génériques, pas un vocabulaire culinaire canonique ni les produits précis vendus en magasin.

La recommandation est donc de conserver un **référentiel canonique interne**, généré et révisé à partir du FCÉN, puis de l'enrichir avec :

- Open Food Facts pour les alias multilingues et le pont vers les produits/code-barres;
- USDA FoodData Central et CIQUAL pour combler les lacunes;
- FoodOn, AGROVOC et éventuellement FoodEx2 comme identifiants et relations sémantiques externes.

Le critère « utilisable dans une recette » doit rester une décision métier de Souschef/Cook, validée contre les vraies recettes et les offres scrapées. Aucune source évaluée ne fournit ce drapeau de façon fiable.

## Comparaison

| Source | Couverture et langue | Identifiants / structure | Accès | Licence | Rôle recommandé |
|---|---|---|---|---|---|
| FCÉN 2026, Santé Canada | 5 993 aliments couramment consommés au Canada; EN/FR | `Food_Code`, 23 groupes, noms et descriptions alternatives bilingues, parfois code USDA | CSV relationnels; l'API documentée porte encore sur 2015 | Licence du gouvernement ouvert – Canada | Socle principal de candidats |
| USDA FoodData Central | Très vaste; surtout anglais; aliments génériques, aliments d'enquête et produits de marque | `fdcId`; NDB, code FNDDS ou GTIN selon le type | API REST et téléchargements CSV/JSON | CC0 / domaine public | Complément de couverture et nutrition |
| CIQUAL 2025 | 3 484 aliments; noms FR/EN; contexte français | `alim_code`; groupes, sous-groupes et sous-sous-groupes | Excel et XML | Licence Ouverte Etalab 2.0 | Traductions et complément générique |
| FoodOn | Plus de 9 600 types de produits alimentaires dans une ontologie beaucoup plus large; surtout anglais | URI `FOODON:*`, hiérarchies et relations OWL | OWL, dépôt GitHub et navigateurs d'ontologie | CC BY 4.0 | Crosswalk sémantique, pas labels UI |
| Open Food Facts | Taxonomie multilingue d'ingrédients et base mondiale de produits; qualité variable | tags canoniques, synonymes, hiérarchie, code-barres produit | API, taxonomie texte, dumps produits | Base ODbL; contenus DbCL | Alias, normalisation d'étiquettes et produits |
| FoodEx2 | Aliments, boissons, commodités, aliments composés et autres domaines de sécurité alimentaire | codes FoodEx2, listes core/extended, neuf hiérarchies et facettes | Catalogue et outils EFSA | Réutilisation EFSA avec attribution; vérifier la notice du catalogue importé | Classification/crosswalk avancé |
| AGROVOC | Plus de 41 400 concepts et plus de 1,219 million de termes, jusqu'à 42 langues; domaine beaucoup plus large que la cuisine | URI SKOS, `broader`/`narrower`, labels multilingues | RDF, navigateur, SPARQL et REST | CC BY 3.0 IGO pour le contenu FAO | Espèces, synonymes et hiérarchie générale |

## 1. Fichier canadien sur les éléments nutritifs 2026

### Pourquoi c'est le meilleur point de départ

Santé Canada présente le FCÉN comme sa base bilingue de composition des aliments couramment consommés au Canada. La publication 2026 contient **5 993 aliments**, jusqu'à **173 nutriments**, et des valeurs moyennes qui ne sont généralement pas propres à une marque. Elle est distribuée sous forme de fichiers CSV relationnels ([présentation officielle du FCÉN](https://www.canada.ca/en/health-canada/services/food-nutrition/healthy-eating/nutrient-data/canadian-nutrient-file-about-us.html), [jeu de données officiel](https://open.canada.ca/data/en/dataset/1b6139bd-ed7e-4043-bc28-ff00e10f3109)).

Le fichier des aliments contient notamment :

- un `Food_Code`;
- une description anglaise et française;
- des descriptions alternatives anglaise et française;
- un code de groupe FCÉN;
- parfois un code USDA NDB et un nom scientifique.

Les fichiers de groupes, mesures et nutriments fournissent également des libellés EN/FR. La documentation de structure explique les tables et leurs relations ([structure de la base](https://www.canada.ca/en/health-canada/services/food-nutrition/healthy-eating/nutrient-data/canadian-nutrient-file-compilation-canadian-food-composition-data-database-structure.html)).

### Limites pour notre usage

Le FCÉN est une base de **composition nutritionnelle**, pas une ontologie d'ingrédients. Une entrée peut désigner une forme crue, cuite, égouttée, salée ou préparée du même aliment. À l'inverse, une entrée « aliment » ne peut pas être décomposée en ingrédients par l'API ([guide officiel de l'API FCÉN](https://produits-sante.canada.ca/api/documentation/cnf-documentation-fr.html)).

Ses 23 groupes comprennent explicitement les aliments pour bébés, sucreries, repas-minute, plats composés et collations, ainsi que les boissons. On peut exclure ces groupes comme première passe, mais pas aveuglément : du chocolat, un bouillon, une tortilla, une boisson végétale ou un jus de citron peuvent être de vrais ingrédients de recette. Le [guide du FCÉN](https://www.canada.ca/en/health-canada/services/food-nutrition/healthy-eating/nutrient-data/canadian-nutrient-file-compilation-canadian-food-composition-data-users-guide.html) décrit les groupes et les codes.

### Accès et licence

La version 2026 doit être importée à partir des CSV ou de l'[archive complète officielle](https://open.canada.ca/data/dataset/1b6139bd-ed7e-4043-bc28-ff00e10f3109/resource/019f2a90-e3a9-489d-b6e1-f74f4ba1d006/download/cnf_fcen_all-files-data_2026.zip). L'API publique documentée renvoie encore les 5 690 entrées de la publication 2015; Santé Canada indique que cette interface reste accessible temporairement pendant la mise en place d'un accès plus convivial à 2026. Il ne faut donc pas bâtir le nouvel import autour de l'ancienne API.

La [Licence du gouvernement ouvert – Canada](https://open.canada.ca/en/open-government-licence-canada) permet de copier, modifier, publier, traduire, adapter et utiliser commercialement les données, avec attribution. Le `Food_Code` doit être conservé comme identifiant externe de provenance, pas utilisé comme identifiant canonique interne.

## 2. USDA FoodData Central

FoodData Central réunit plusieurs types de données qui répondent à des objectifs différents :

- **Foundation Foods** : aliments de base non transformés ou peu transformés;
- **SR Legacy** : ancien référentiel générique, finalisé en 2018;
- **FNDDS** : aliments et boissons rapportés dans les enquêtes alimentaires, incluant de nombreux plats;
- **Branded Foods** : produits commerciaux fournis par l'industrie;
- **Experimental Foods** : données provenant de travaux scientifiques.

Cette séparation est officielle dans la [documentation des types de données](https://fdc.nal.usda.gov/data-documentation/). Foundation Foods et SR Legacy sont les plus intéressants pour les ingrédients génériques. FNDDS est utile pour comprendre les expressions de consommation mais introduit beaucoup de plats composés. Branded Foods peut aider au niveau produit, mais inclut massivement boissons, collations et produits hors recette; les marchés documentés sont principalement les États-Unis et la Nouvelle-Zélande, pas le Canada ([documentation Branded Foods](https://fdc.nal.usda.gov/GBFPD_Documentation/)).

Les identifiants ne forment pas un canon transversal unique : `fdcId` identifie un enregistrement publié, NDB sert pour Foundation/SR, un code à huit chiffres identifie les aliments FNDDS, et GTIN identifie les produits de marque. Une modification d'un enregistrement peut produire un nouveau `fdcId` ([aide FoodData Central](https://fdc.nal.usda.gov/help/)).

L'[API REST](https://fdc.nal.usda.gov/api-guide/) offre recherche et détails, exige une clé data.gov et applique par défaut 1 000 requêtes par heure et par IP. Les jeux sont aussi disponibles en [CSV et JSON téléchargeables](https://fdc.nal.usda.gov/download-datasets/). Les données sont dans le domaine public sous **CC0**; l'USDA demande néanmoins d'être citée comme source.

Verdict : excellent complément anglophone et nutritionnel, mais mauvais vocabulaire maître pour une application canadienne bilingue.

## 3. Table CIQUAL 2025

La table de l'Anses contient **3 484 aliments** et **74 constituants** dans sa version 2025 ([présentation officielle](https://ciqual.anses.fr/cms/en/2025-anses-ciqual-table)). Les fichiers attribuent à chaque aliment un `alim_code`, un nom français, un nom anglais et des codes de groupe, sous-groupe et sous-sous-groupe. La [documentation technique 2025](https://ciqual.anses.fr/cms/sites/default/files/inline-files/Table%20Ciqual%202025%20doc%20FR_2025_11_19.pdf) décrit les fichiers Excel et XML et leurs champs.

La table est presque entièrement générique, mais son contexte est la consommation en France. Elle comprend aussi des aliments cuits, plats ou produits finis, biscuits, gâteaux et boissons. Elle n'offre ni GTIN, ni prix, ni liste dédiée aux ingrédients de recettes.

Les [fichiers officiels](https://entrepot.recherche.data.gouv.fr/dataset.xhtml?persistentId=doi:10.57745/RDMHWY) sont publics en Excel et XML sous **Licence Ouverte Etalab 2.0**, avec citation explicite de l'Anses demandée.

Verdict : très utile pour enrichir les noms FR/EN, vérifier les distinctions alimentaires et obtenir des données nutritionnelles, mais à utiliser comme source secondaire puisque le marché cible est canadien.

## 4. FoodOn

FoodOn est une ontologie ouverte destinée à nommer les matières et produits alimentaires, leurs origines anatomiques et taxonomiques, les transformations et d'autres notions de la chaîne « de la ferme à l'assiette ». Son dépôt fournit des URI stables `FOODON:*`, des relations OWL, des synonymes et une version stable téléchargeable ([dépôt officiel FoodOn](https://github.com/FoodOntology/foodon)).

La hiérarchie principale comprend plus de **9 600 produits alimentaires**, mais l'ontologie complète couvre beaucoup plus que des ingrédients culinaires : organismes, parties anatomiques, procédés, aliments pour animaux et schémas de classification ([structure de FoodOn](https://foodon.org/design/foodon-structure/)). Sa couverture française est très faible comparée à l'anglais. Elle est publiée sous [CC BY 4.0](https://github.com/FoodOntology/foodon/blob/master/LICENSE.txt).

Verdict : bonne colonne `foodon_id` et bonne source de parentage sémantique; trop large, complexe et peu bilingue pour devenir directement le registre affiché dans Souschef/Cook.

## 5. Open Food Facts

Open Food Facts apporte deux ressources distinctes :

1. une base collaborative de produits précis avec codes-barres, noms, marques, catégories et listes d'ingrédients;
2. une taxonomie multilingue d'ingrédients utilisée pour normaliser ces listes.

La taxonomie relie un tag canonique à des traductions et synonymes; par exemple `en:sugar` peut être affiché comme « sucre » en français. L'API expose des opérations de canonicalisation et d'affichage multilingue ([documentation officielle de la taxonomie](https://openfoodfacts.github.io/documentation/docs/Product-Opener/v3/taxonomy/get-api-v3-taxonomy-display-tags/)). Le [fichier source de la taxonomie d'ingrédients](https://github.com/openfoodfacts/openfoodfacts-server/blob/main/taxonomies/food/ingredients.txt) contient également de la hiérarchie et divers liens/propriétés, dont certains codes CIQUAL.

Cette taxonomie reflète les ingrédients rencontrés sur les emballages. Elle contient donc des additifs, agents de traitement et composés industriels qui ne sont pas des ingrédients qu'un utilisateur achèterait normalement pour une recette. La base produits est alimentée volontairement par la communauté; Open Food Facts précise qu'elle n'en garantit ni l'exactitude, ni l'exhaustivité, ni la fiabilité ([introduction à l'API](https://openfoodfacts.github.io/documentation/docs/Product-Opener/api/)).

Pour quelques produits, on peut employer l'API; au-delà de quelques centaines, Open Food Facts demande d'utiliser les exports CSV/JSONL. La base est sous **ODbL**, son contenu sous **DbCL**, et ses images sous **CC BY-SA**. L'ODbL peut imposer attribution et partage à l'identique d'une base dérivée; la couche Open Food Facts doit donc rester identifiable et son mode d'intégration doit être validé avant de fusionner des données dans un canon redistribué.

Verdict : meilleure source évaluée pour les alias d'étiquettes et le rapprochement `code-barres/produit → ingrédient canonique`, mais pas pour définir seule le canon.

## 6. FoodEx2

FoodEx2 est le système standardisé de l'Autorité européenne de sécurité des aliments (EFSA). Il organise de nombreux aliments individuels en groupes et catégories parent-enfant, avec une liste centrale, une liste étendue, neuf hiérarchies et des facettes permettant de préciser un aliment ([présentation officielle FoodEx2](https://www.efsa.europa.eu/en/data/data-standardisation)).

Il est conçu pour harmoniser la collecte de données de consommation, de composition et d'exposition aux risques. Son périmètre inclut donc aliments composés, boissons, alimentation animale et catégories techniques. Son catalogue et ses outils sont plus lourds qu'un simple registre culinaire, et son vocabulaire de travail est principalement anglais.

Les catalogues sont consultables avec les outils EFSA. La [notice générale de réutilisation de l'EFSA](https://www.efsa.europa.eu/en/legalnotice) autorise la réutilisation avec attribution, sauf conditions particulières indiquées sur un document ou jeu précis. Pour tout import automatisé, il faut enregistrer la version du catalogue et vérifier sa notice de licence propre au moment du téléchargement.

Verdict : utile si Souschef a plus tard besoin d'une classification alimentaire normalisée ou de facettes détaillées; disproportionné pour amorcer la liste canonique.

## 7. AGROVOC

AGROVOC est le thésaurus SKOS multilingue de la FAO. Il contient plus de **41 400 concepts** et **1,219 million de termes** dans jusqu'à 42 langues, avec URI, labels et relations sémantiques ([présentation officielle AGROVOC](https://www.fao.org/agrovoc/about)). L'anglais et le français sont bien représentés.

Il couvre toute l'agriculture et les domaines de la FAO : aliments, espèces, cultures, nutrition, procédés, foresterie, aquaculture, économie et autres thèmes. Cette largeur le rend utile pour relier « pois chiche » à une espèce ou récupérer des synonymes, mais beaucoup trop général pour distinguer toutes les formes commerciales et culinaires pertinentes.

Il est accessible par téléchargement RDF, navigateur, [SPARQL et API REST](https://www.fao.org/agrovoc/access). Le contenu FAO est disponible sous **CC BY 3.0 IGO**; la licence et l'attribution doivent être conservées lors d'extractions.

Verdict : source complémentaire de terminologie et d'espèces, pas registre d'ingrédients achetables.

## Architecture recommandée pour Souschef/Cook

### Garder quatre objets distincts

```text
libellé de recette ──alias──> ingrédient canonique interne
                                      │
                                      ├── crosswalks FCÉN / CIQUAL / USDA / FoodOn / AGROVOC
                                      │
produit précis (GTIN, marque, format) ─┘
                 │
                 └── offre scrapée (magasin, prix, date)
```

Un ingrédient canonique doit représenter une **identité d'achat utile à la recette**, pas une ligne nutritionnelle, un mot d'étiquette ou un produit de marque.

Champs minimaux suggérés :

- `canonical_ingredient_id` interne, stable et indépendant des sources;
- `name_fr_ca` et `name_en_ca`;
- catégorie métier (`produce`, `meat`, `dairy`, `pantry`, etc.);
- forme achetable pertinente (`fresh`, `dried`, `canned`, `powder`, etc.);
- alias avec langue, région, provenance et statut de validation;
- indicateurs de pertinence recette et de possibilité d'achat;
- identifiants externes versionnés (`cnf_food_code`, `ciqual_code`, `fdc_id`/`ndb`, `foodon_uri`, `agrovoc_uri`, etc.);
- statut de curation (`candidate`, `approved`, `deprecated`, `needs_review`).

### Pipeline conseillé

1. Importer les 5 993 lignes du CSV FCÉN 2026 dans une table de **candidats externes**, sans les convertir automatiquement en ingrédients canoniques.
2. Exclure initialement les groupes `Babyfoods`, `Sweets`, `Fast Foods`, `Mixed Dishes` et `Snacks`; mettre `Beverages` en révision sélective.
3. Comparer les candidats aux libellés réellement présents dans les recettes de Cook/Souschef.
4. Regrouper les variantes qui ne changent pas l'achat, mais séparer celles qui désignent un produit différent : ail frais/poudre, tomate fraîche/conserve/pâte, basilic frais/séché, crème/crème sure, etc.
5. Ajouter les alias EN/FR utiles depuis les recettes et, avec une provenance explicite, depuis Open Food Facts, CIQUAL et AGROVOC.
6. Conserver les produits de marque, GTIN, formats et magasins dans la couche produit. Un produit peut pointer vers un ingrédient canonique; il ne doit pas devenir cet ingrédient.
7. Mesurer la couverture sur deux corpus : lignes de recettes et offres scrapées. Réviser en priorité les libellés fréquents non résolus ou ambigus.

### Critère de réussite

Le nombre total d'ingrédients n'est pas le meilleur indicateur. Les métriques utiles sont :

- pourcentage de lignes de recettes reliées avec confiance;
- pourcentage d'ingrédients canoniques reliés à au moins un produit achetable lorsque pertinent;
- taux de correspondances ambiguës ou corrigées manuellement;
- couverture EN-CA/FR-CA;
- traçabilité de chaque alias et crosswalk externe.

Un objectif initial raisonnable est de viser **95 à 98 % des lignes d'ingrédients des recettes réelles**, plutôt qu'un nombre arbitraire de 500 ou 1 000 entrées.

## Décision proposée

Adopter le FCÉN 2026 comme **source d'amorçage**, pas comme table canonique finale. Souschef/Cook reste propriétaire de ses identifiants et de sa notion d'« ingrédient de recette achetable ». Open Food Facts sert de couche d'alias et de produits, tandis que les autres référentiels restent des crosswalks versionnés.

Cette approche donne le meilleur équilibre entre contexte canadien, bilinguisme, licence ouverte, couverture culinaire et capacité future à rapprocher les offres de circulaires.

## Intégration francophone du FCÉN 2026

### La version française est déjà comprise

Il n'y a pas un jeu de données français distinct à traduire ou à maintenir. Le FCÉN 2026 est publié comme une base **bilingue** : les libellés français et anglais sont présents sur la même ligne dans les CSV. Santé Canada confirme que la publication compte 5 993 aliments et qu'elle est distribuée sous forme de fichiers relationnels CSV compatibles avec Excel ([page francophone officielle](https://www.canada.ca/fr/sante-canada/services/aliments-nutrition/saine-alimentation/donnees-nutritionnelles/fichier-canadien-elements-nutritifs-propos-nous.html), [jeu de données officiel](https://open.canada.ca/data/en/dataset/1b6139bd-ed7e-4043-bc28-ff00e10f3109)).

Deux moyens officiels conviennent à l'import :

- télécharger l'[archive complète `cnf_fcen_all-files-data_2026.zip`](https://open.canada.ca/data/dataset/1b6139bd-ed7e-4043-bc28-ff00e10f3109/resource/019f2a90-e3a9-489d-b6e1-f74f4ba1d006/download/cnf_fcen_all-files-data_2026.zip), recommandée pour un import reproductible;
- télécharger seulement [`food_name.csv`](https://open.canada.ca/data/dataset/1b6139bd-ed7e-4043-bc28-ff00e10f3109/resource/e1ffee62-58cb-4e3e-b359-115c658388ad/download/food_name.csv) et [`cnf_food_group.csv`](https://open.canada.ca/data/dataset/1b6139bd-ed7e-4043-bc28-ff00e10f3109/resource/adc5b26e-14ea-4697-b208-bbb311955c81/download/cnf_food_group.csv) pour une première liste de candidats plus légère.

L'archive officielle a été inspectée directement le 12 août 2026. Elle contient neuf CSV et les guides 2026 en français et en anglais. Les neuf CSV sont encodés en **UTF-8 avec BOM**, utilisent la **virgule** comme séparateur et les guillemets doubles pour protéger les valeurs qui contiennent une virgule. Il faut donc ouvrir les fichiers explicitement en UTF-8 et employer un vrai lecteur CSV, et non découper les lignes avec `split(',')`.

### Champs à importer

Le fichier `Food_Name.csv` contient exactement ces colonnes en 2026 :

```text
Food_Code
Food_Description_EN
Food_Description_FR
Alternate_Description_EN
Alternate_Description_FR
Food_Source_Code
USDA_NDB_Code
CNF_Food_Group_Code
Comment_EN
Comment_FR
ScientificName
Food_Last_Updated_Date
```

Les 5 993 lignes possèdent toutes une valeur dans `Food_Description_FR` et dans `Food_Description_EN`; 2 259 ont aussi une `Alternate_Description_FR` non vide. Ces comptes proviennent d'une lecture directe de l'[archive officielle 2026](https://open.canada.ca/data/dataset/1b6139bd-ed7e-4043-bc28-ff00e10f3109/resource/019f2a90-e3a9-489d-b6e1-f74f4ba1d006/download/cnf_fcen_all-files-data_2026.zip).

Pour l'usage de Souschef, la correspondance recommandée est :

| Champ FCÉN | Usage dans Souschef |
|---|---|
| `Food_Code` | identifiant externe stable `cnf_food_code`; ne pas en faire l'identifiant canonique interne |
| `Food_Description_FR` | nom français du candidat et libellé principal de curation |
| `Food_Description_EN` | nom anglais correspondant |
| `Alternate_Description_FR` | candidats d'alias français, à séparer et réviser plutôt qu'à accepter automatiquement |
| `Alternate_Description_EN` | candidats d'alias anglais |
| `CNF_Food_Group_Code` | clé de filtrage et de catégorisation |
| `Food_Source_Code` | provenance FCÉN, reliée à `Food_Source.csv` |
| `USDA_NDB_Code` | crosswalk USDA lorsqu'il est fourni |
| `Comment_FR` | contexte de curation; ne pas l'afficher comme partie du nom |
| `ScientificName` | crosswalk taxonomique facultatif |
| `Food_Last_Updated_Date` | traçabilité et détection des mises à jour |

`Food_Code` est unique dans les 5 993 lignes inspectées. Dans les fichiers relationnels 2026, il relie notamment `Food_Name.csv` à `Measure_Weight_Conversion.csv` et `Nutrient_Amount.csv`; `CNF_Food_Group_Code` relie l'aliment à `CNF_Food_Group.csv`. La [documentation structurelle officielle 2026 en français](https://open.canada.ca/data/dataset/1b6139bd-ed7e-4043-bc28-ff00e10f3109/resource/220e51d5-4db4-43ba-ae72-497ccb4fcf24/download/fichier-canadien-sur-les-elements-nutritifs_structure-de-la-base-de-donnees-et-description-du-co.pdf) décrit le rôle et les relations de ces fichiers.

Le schéma exact du fichier de groupes est :

```text
CNF_Food_Group_Code
CNF_Food_Group_Description_EN
CNF_Food_Group_Description_FR
```

Il contient 23 groupes bilingues. Pour une première passe orientée « ingrédients de recette », on peut mettre en quarantaine les codes `3` (Aliments pour bébés), `19` (Sucreries), `21` (Aliments prêts-à-manger), `22` (Mets composés) et `25` (Grignotises), puis examiner manuellement le code `14` (Boissons). Ce filtre doit produire des **candidats**, pas supprimer définitivement les lignes : des produits de boulangerie, sauces, boissons ou sucreries peuvent aussi servir d'ingrédients.

### Fichiers facultatifs utiles aux recettes et aux prix

Pour convertir les formats rencontrés dans les recettes ou les offres, on peut ajouter les ressources officielles suivantes :

- [`measure_name.csv`](https://open.canada.ca/data/dataset/1b6139bd-ed7e-4043-bc28-ff00e10f3109/resource/104adbc9-f4cc-40b1-9aaa-08290648e24b/download/measure_name.csv) : `Measure_Code`, `Measure_Description_and_Unit_EN`, `Measure_Description_and_Unit_FR`;
- [`measure_type.csv`](https://open.canada.ca/data/dataset/1b6139bd-ed7e-4043-bc28-ff00e10f3109/resource/e7eac9fc-b46c-4c18-8729-b962d2412fec/download/measure_type.csv) : `Measure_Type_Code`, `Measure_Type_Description_EN`, `Measure_Type_Description_FR`;
- [`measure_weight_conversion.csv`](https://open.canada.ca/data/dataset/1b6139bd-ed7e-4043-bc28-ff00e10f3109/resource/bb76d816-3ac0-4749-8c4b-f0dbfd0fac76/download/measure_weight_conversion.csv) : `Food_Code`, `Measure_Type_Code`, `Measure_Code`, `Measure_Weight_Conversion`, `Measure_Weight_Conversion_Last_Updated_Date`;
- [`food_source.csv`](https://open.canada.ca/data/dataset/1b6139bd-ed7e-4043-bc28-ff00e10f3109/resource/53819b2a-bf8e-40c1-9a12-0c8897d6dc76/download/food_source.csv) : descriptions bilingues de la provenance des données.

Les tables de nutriments ne sont pas nécessaires pour construire la liste canonique. Elles peuvent être ajoutées plus tard si Souschef veut aussi calculer les valeurs nutritionnelles.

### Choix d'intégration dans Souschef actuel

L'état actuel du dépôt impose de ne pas confondre import externe et catalogue approuvé :

- `seed/main/canonical_ingredients.json` est versionné et chargé directement par `backend/app/seeding/seed.py`, avec un upsert sur `id`;
- `catalog.CanonicalIngredient` ne possède pour l'instant qu'un `name` (français), sans colonnes d'alias, de langue, de groupe FCÉN ou de provenance;
- chaque ligne canonique exige aussi `unit_kind`, `base_unit`, `perishability`, `salvage_value_cents_per_base_unit` et éventuellement `density_g_per_ml`, données que le FCÉN ne fournit pas sous cette forme;
- le seul staging actuel, `staging.RawOffer`, est propre aux offres scrapées et ne doit pas recevoir des aliments FCÉN;
- `scripts/generate_seed.py` régénère les jeux `seed/main` et `seed/toy`; tout futur export canonique doit donc être intégré à ce générateur ou placé dans un générateur séparé explicite, sinon une régénération pourrait l'écraser.

Trois modes sont possibles :

| Mode | Avantages | Limites | Verdict |
|---|---|---|---|
| Importer directement dans le JSON canonique versionné | Déploiement simple; compatible avec le seeder actuel | Oblige à inventer les champs métier manquants; mélange 5 993 aliments nutritionnels et ingrédients approuvés; aucune place pour les alias/crosswalks | À éviter pour l'import brut; garder le JSON seulement comme **sortie curée** |
| Ajouter une table de candidats/staging FCÉN | Conserve la source brute, les deux langues, les statuts de révision et la traçabilité; permet un rejeu idempotent | Demande une migration, un modèle et un importeur dédiés | **Approche recommandée** pour le travail de curation |
| Interroger une API FCÉN à l'exécution | Pas de snapshot local | La publication conviviale/API disponible reste celle de 2015; résultats non reproductibles et dépendance réseau dans le chemin applicatif | À exclure pour 2026 |

La cible recommandée est donc un pipeline **hors requête HTTP** :

```text
archive officielle 2026 + somme SHA-256
    -> tables candidates FCÉN (copie fidèle, bilingue)
    -> filtrage et décisions de curation versionnées
    -> alias + crosswalk Food_Code
    -> canonical_ingredients.json approuvé
    -> seeding idempotent existant
```

Lors de l'implémentation, une migration devrait créer des tables dédiées telles que `staging.cnf_food_candidate` et `catalog.canonical_ingredient_external_ref` (et une table d'alias), plutôt que de réutiliser `staging.raw_offer`. Le candidat garderait au minimum tous les champs de `Food_Name.csv`, le nom de l'édition, la somme de l'archive et un statut de curation. Le crosswalk devrait avoir une contrainte unique sur `(source, external_id, source_version)`; plusieurs `Food_Code` peuvent légitimement être regroupés sous un même ingrédient canonique interne.

Le résultat **approuvé seulement** peut continuer d'être exporté dans `seed/main/canonical_ingredients.json`, avec les slugs internes existants et tous les champs métier remplis explicitement. Pour offrir réellement une interface bilingue, il faudra toutefois faire évoluer le modèle canonique vers `name_fr_ca` et `name_en_ca`, ou ajouter une table de libellés localisés; copier `Food_Description_FR` dans l'actuel champ `name` suffit uniquement pour une première interface francophone.

### Mise en œuvre recommandée

1. Enregistrer l'URL officielle, l'édition `2026`, la date de téléchargement et le SHA-256 de l'archive dans les métadonnées d'import. L'archive téléchargée le 12 août 2026 avait le SHA-256 `F5FAAD8977EE6BBDD9D69C8649077CACD87D8658AD200509A4047DB1E29EDCDD`; le pipeline doit toutefois recalculer et enregistrer la somme à chaque import plutôt que la figer comme garantie future.
2. Charger les lignes sans modification dans une table de staging FCÉN dédiée `cnf_food_candidate`, jamais dans `raw_offer`; conserver les deux langues, même si l'interface initiale est francophone.
3. Afficher `Food_Description_FR` aux curateurs et employer `Alternate_Description_FR` uniquement comme source d'alias proposés.
4. Appliquer le filtre de groupes comme statut (`candidate`, `review`, `excluded`) plutôt que comme suppression.
5. Comparer les candidats aux ingrédients réellement présents dans les recettes; créer ou fusionner les ingrédients canoniques après révision.
6. Conserver `Food_Code` dans une table de crosswalk afin qu'un ingrédient canonique interne puisse pointer vers zéro, un ou plusieurs aliments FCÉN.
7. Exporter uniquement les ingrédients approuvés vers le JSON de seed, puis exécuter deux fois le seeder et vérifier que le second passage ne change ni le nombre de lignes ni les associations.
8. Attribuer la source conformément à la [Licence du gouvernement ouvert – Canada](https://open.canada.ca/fr/licence-du-gouvernement-ouvert-canada).

Il ne faut pas utiliser l'API FCÉN actuelle pour cet import : l'[interface publique documentée](https://produits-sante.canada.ca/api/documentation/cnf-documentation-fr.html) et l'outil de recherche en ligne portent encore sur l'édition 2015. Pour Souschef, la source reproductible est donc le jeu de CSV 2026.
