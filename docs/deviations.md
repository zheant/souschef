# Écarts assumés par rapport à `docs/spec.md`

La spécification n'est jamais modifiée ; chaque écart est consigné ici avec sa
raison, conformément à la consigne de la spec elle-même.

## D1 — `app/main.py` n'expose qu'un `/api/health` (étape 1)

**Écart.** La spec définit l'API complète (section « API »), mais `main.py` ne
sert qu'un contrôle de santé.

**Raison.** L'ordre de livraison place l'API à l'étape 5. Un endpoint minimal
est néanmoins nécessaire dès l'étape 1 pour que `docker compose up` démarre la
pile complète (api, db, web) en une commande, comme exigé par la section
« Stack imposée ». L'API métier remplacera ce fichier à l'étape 5 sans
migration ni changement d'orchestration.

**Levé à l'étape 5** : les dix endpoints de la spec sont exposés, `/api/health`
conservé.

## D2 — Front-end réduit à un squelette de démarrage (étape 1)

**Écart.** Le service `web` du compose sert une page unique qui vérifie la
santé de l'API, pas les cinq écrans spécifiés.

**Raison.** Même logique que D1 : la SPA est l'étape 6, mais le compose doit
démarrer les trois services dès maintenant. Le squelette fixe déjà la chaîne
Vite + TypeScript + proxy `/api`, qui ne changera pas.

**Levé à l'étape 6** : les cinq écrans de la spec sont livrés.

## D3 — Noms de colonnes enrichis d'unités

**Écart.** Certaines colonnes ne portent pas le nom littéral de la spec :

| Spec | Implémentation |
|---|---|
| `price` | `price_cents_cad` |
| `regular_price` | `regular_price_cents_cad` |
| `salvage_value_per_unit` | `salvage_value_cents_per_base_unit` |
| `time_value_per_hour` | `time_value_cents_per_hour` |
| `package_size` | `package_qty_in_base_unit` |
| `qty_fixed_per_batch` | `qty_fixed_per_batch_base_unit` |
| `qty_marginal_per_serving` | `qty_marginal_per_serving_base_unit` |
| `quantity` (pantry) | `quantity_base_unit` |
| `max_prep_time_per_meal` | `max_prep_time_per_meal_h` |

**Raison.** La section « Exigences transverses » impose que les unités
apparaissent dans les noms de champs et qu'aucun montant d'argent ne soit un
flottant. Les correspondances avec les symboles mathématiques ($c_{ps}$,
$\sigma_i$, $\kappa$, $v_p$, …) sont documentées dans les docstrings des
modèles. Ce n'est pas un écart de modèle, seulement de nommage.

## D4 — $\sigma_i$ en `Numeric` (Decimal) plutôt qu'en cents entiers

**Écart.** `salvage_value_cents_per_base_unit` est un `Numeric(14, 6)` et non
un entier.

**Raison.** La valeur résiduelle par **gramme** ou **millilitre** est
sub-cent (ex. riz ≈ 0,28 ¢/g). La spec autorise explicitement « entiers en
cents, **ou `Decimal`** » ; l'unité reste le cent, jamais de flottant.

## D5 — Clés primaires « naturelles » (slugs texte), restreintes à `catalog`
*(révisé au point de contrôle de l'étape 2 — veto partiel)*

**Écart.** La spec dit simplement `id`. L'implémentation utilise des slugs
texte stables comme clés primaires **uniquement pour les entités curées** :
`canonical_ingredient`, `recipe` (schéma `catalog`) et `household_profile`.

**Résolution du veto.** Les slugs en clé primaire ont été refusés pour
`market` au point de contrôle : les produits scrapés n'auront pas de slug
stable, et c'est `product_mapping` qui absorbe cette instabilité. `store`,
`product` et `price` utilisent donc des **clés de substitution entières** ;
`store` et `product` portent une colonne `external_key` unique (le slug),
cible du `ON CONFLICT` au seeding. La résolution `external_key` → clé de
substitution vit dans la normalisation (`app/ingestion/normalize.py`).

## D6 — `seed/` organisé en `seed/main/` et `seed/toy/`

**Écart.** La spec mentionne `seed/` et « une instance jouet séparée ».

**Raison.** La séparation en deux répertoires rend l'instance jouet chargeable
par la même commande de seeding (`--seed-dir seed/toy`) et par les tests de
l'étape 4, sans mélange avec le jeu principal.

## D7 — Colonne `payload_fingerprint` ajoutée à `staging.raw_offer`

**Écart.** La spec définit `payload` + `mapping_status` ; une empreinte sha256
du payload a été ajoutée.

**Raison.** La spec exige qu'un retraitement soit « rejouable sans reperdre
les données » : l'empreinte donne une clé d'unicité `(magasin, semaine,
empreinte)` qui rend l'atterrissage idempotent au rejeu, sans interpréter le
payload.

## D8 — Prix réguliers déterministes par (magasin, produit) dans le générateur
*(ajouté au point de contrôle de l'étape 2)*

**Écart.** Rien dans la spec n'impose la structure statistique du générateur
de seeds ; consigné par transparence.

**Raison.** La première version tirait le facteur de prix par **offre**, si
bien que les prix réguliers fluctuaient aléatoirement d'une semaine à l'autre
— rendant l'historique incapable de remplir son rôle (« distinguer un vrai
rabais d'un prix régulier annoncé en gros caractères », table `price`).
L'assortiment et le prix régulier sont désormais déterministes par couple
(magasin, produit) et stables sur les 4 semaines ; seules les promotions
(~25 % par semaine, profondeur 20–35 %) varient.

*Étendu au point de contrôle (dispersion inter-magasins).* Le facteur par
couple s'appuie sur un positionnement par bannière
(`STORE_PRICE_FACTOR` : Maxi-Prix 0,85 — escompte systématique mais éloigné ;
Épicier du Coin 1,12 — dépanneur cher mais proche) plus un jitter de ±5 % par
couple, portant le RSD inter-magasins à ~9,6 % médian (plage 0–17 %). La
variance temporelle reste nulle.

**Note assumée** : le haut de plage (~17 % de RSD, soit un rapport jusqu'à
~1,45 entre bannières sur un même produit) est élevé pour du prix régulier.
C'est un choix délibéré validé au point de contrôle — cumul du positionnement
par bannière et du jitter par couple — pour que les écarts de prix réguliers
puissent réellement disputer un second arrêt à f_marg. Ne pas le prendre plus
tard pour un bug de génération.

*Étendu au point de contrôle (calibration de σ_i).* σ_i n'est plus une valeur
manuelle mais est **calibré par le générateur contre les prix générés** :
σ_i = ratio_cible × 0,8 × min(c_ps(1+t_p)/v_p) sur la semaine courante, avec
ratio_cible = 0,93 pour le riz (unique cas volontairement proche de la borne),
0 pour coriandre et épinards, et un tirage déterministe dans [0,50 ; 0,80]
pour les autres. L'assertion 1 tient ainsi **par construction**, et reste
vraie à chaque changement du paysage de prix du seed.


## D9 — Demande encadrée : ⌈D⌉ ≤ Σx_r ≤ ⌈D(1+ε)⌉
*(décision du propriétaire de la spec au point de contrôle de l'étape 2)*

**Écart.** La spec pose Σ_r x_r = D. L'égalité est remplacée par
l'encadrement ⌈D⌉ ≤ Σ_r x_r ≤ ⌈D(1+ε)⌉, avec ε dans `household_profile`
(`demand_slack_epsilon`, défaut 0,10), surchargeable par `SolverConfig`.

**Raison.** Le problème est l'égalité, pas l'intégralité : les ρ_h sont des
coefficients d'appétit, et exiger que n_repas·Σρ_h tombe sur un entier
interdirait des profils légitimes (deux adultes + un enfant sur 14 repas
donnent D = 36,4) avec un message d'erreur incompréhensible. La borne basse
garantit que le ménage mange, la borne haute empêche la surproduction, et la
marge donne au solveur la latitude d'ajuster les portions aux formats
d'emballage — arbitrage que l'égalité stricte lui interdisait.

**Conséquences propagées.** L'assertion 6 (R_min·min β) se teste contre la
borne basse ⌈D⌉ ; la capacité entière contre la borne haute (plafond par
recette min(⌊α·⌈D(1+ε)⌉⌋, m_r)) ; R_min ≥ ⌈1/α⌉ est bien un ≥ (l'égalité
passe, couverte par un test). Le profil de seed conserve ρ = (1,0 ; 1,0 ; 0,6)
et sert de cas de test permanent du D non entier
(`tests/test_demand.py::test_non_integer_D_from_seed_profile`).

## D10 — Champ `taste_preferences` ajouté à `household_profile`
*(ajouté à l'étape 3)*

**Écart.** La spec ne définit aucun champ pour stocker les préférences
gustatives, mais le scoring d'appétence exige la « correspondance des tags aux
préférences déclarées ».

**Raison.** Sans stockage, les préférences déclarées n'existent nulle part.
Champ JSONB `{"liked_tags": [...], "disliked_tags": [...]}`, dans l'esprit du
« modèle complet dès maintenant ». Il est édité par l'écran Ménage à
l'étape 6.

## D11 — Sémantiques précisées à l'étape 4 (solveur)
*(interprétations là où la spec laissait un point ouvert ; aucune formule
imposée n'est modifiée)*

- **Filtre de temps du préfiltrage** *(directive du point de contrôle de
  l'étape 3)* : contrainte de **session** — τ^fixe_r + β_r·τ^marg_r ≤
  `max_prep_time_per_meal` (le temps réel du plus petit lot possible), et non
  l'amortissement par portion. κ gère l'arbitrage sur le temps moyen dans
  l'objectif ; le filtre dur écarte les séances trop longues. Test
  discriminant : `test_prep_time_is_a_session_constraint`.
- **`enable_batch_fixed_cost = False`** retire le mécanisme de lot complet :
  δ_r et τ^fixe_r (spec), mais aussi â^fixe_ir (lié à δ_r dans la couverture)
  et la borne β_r·δ_r. Si la diversité est active, un indicateur binaire δ_r
  subsiste avec le lien minimal x_r ≥ δ_r — sans lui, Σδ ≥ R_min se
  satisferait de recettes vides.
  **Signalement obligatoire** *(point de contrôle de l'étape 4)* : ce drapeau
  — comme `enable_pantry_stock` (g_i) — modifie l'équation de couverture des
  ingrédients, pas seulement l'objectif : les paniers ne sont pas comparables
  entre configurations qui en diffèrent. Le rapport de diagnostic sépare
  explicitement les drapeaux actifs en `alterent_les_besoins_en_ingredients`
  et `objectif_ou_contraintes_seulement` (champ `flag_effects`, testé).
- **`enable_multi_store = False`** : magasin unique = celui de
  `single_store_external_key` si fourni, sinon le plus proche du domicile
  (règle déterministe) ; z_s, y et tous les coûts de déplacement retirés.
- **Plafond de part avec la demande encadrée (suite de D9)** :
  x_r ≤ α·⌈D(1+ε)⌉ — coefficient constant, cohérent avec la vérification de
  capacité 6b. Le Big-M agrégé M_ps est également évalué avec la borne haute
  (borne valide, jamais trop serrée).
- **Centre commercial dans le MILP** : le rabais du second arrêt (1,50 $ →
  0,25 $, distance non recomptée) est linéarisé par centre : coût =
  Σ_c v_c·(125 + 156·d_c) + Σ_s 25·z_s avec v_c ≥ z_s. Pour un centre à
  magasin unique, la somme redonne exactement 150 + 156·d_s (testé).
- **Gap MIP atteint** : CBC via PuLP n'expose pas la borne duale ; le
  diagnostic rapporte le gap demandé et `mip_gap_attained = None`, le statut
  « Optimal » de CBC garantissant gap ≤ demandé.
- **Couvertures « saturées » du diagnostic** : seules les couvertures
  d'ingrédients au besoin strictement positif sont rapportées — un slack nul
  sur 0 ≥ 0 ne contraint rien.


## D12 — Table `household.plan` ajoutée
*(ajouté à l'étape 5)*

**Écart.** Le modèle de données de la spec ne définit pas de table de plans,
mais son API l'exige : `GET /api/plan/{id}` et `POST /api/plan/{id}/commit`
supposent des plans persistés.

**Raison.** Le plan stocke, figés à la résolution : la `SolverConfig`
sérialisée (le commit dépend de `enable_pantry_stock` et
`enable_batch_fixed_cost`), les portions et δ_r, les lignes d'achat, les
**besoins par ingrédient** (pour un commit déterministe sans recalcul du
solveur), et le diagnostic complet. Les recettes des derniers plans commis
alimentent la pénalité de répétition du scoring — la boucle promise à
l'étape 3 est fermée.

## D13 — Valeur du stock consommé au rapport de diagnostic
*(décision du point de contrôle de l'étape 5)*

**Retirée depuis (D19)** : le garde-manger à quantité suivie (`pantry_stock`)
a été retiré en entier lors du pivot vers les essentiels (staples,
`CLAUDE.md`, section « Pilote — garde-manger retiré »). `pantry_consumed_by_ingredient`,
`pantry_consumed_value_cents` et `enable_pantry_stock`, tous les trois
décrits ci-dessous, n'existent plus dans le code — `Diagnostic` n'a plus
cette distinction du tout, un essentiel étant acheté comme n'importe quel
autre ingrédient (voir D19 pour ce qui gère maintenant la pression vers les
périssables). Laissée ici telle quelle comme trace de l'état au moment de
cette décision historique, même convention que D15→D18.

**Écart.** Le rapport de diagnostic de la spec ne distingue pas décaissement
et coût réel. Champs ajoutés : `pantry_consumed_by_ingredient` et
`pantry_consumed_value_cents` = Σ_i min(g_i, besoin_i)·c̄_i, avec c̄_i le
prix unitaire taxé minimum courant.

**Raison.** La fonction objectif minimise le décaissement de la semaine — un
plan à 19,70 $ après un commit n'est pas une économie mais la consommation
d'un stock payé la semaine précédente. Sans cette distinction, l'écran
Résultat afficherait un gain inexistant puis une remontée inexpliquée au
cycle suivant. Le front affiche les deux lectures (« X $ dépensés, dont Y $
de garde-manger déjà payé »). Vérifié à la main sur le jouet
(400 g × 0,30 c/g = 120 c) et nul quand `enable_pantry_stock` est inactif.

## D14 — `pyproject.toml` : découverte de paquets explicite
*(corrigé lors d'une session de prise de connaissance, après la livraison)*

**Écart.** Aucune section `[tool.setuptools]` ne bornait la découverte de
paquets ; `pip install -e .` échouait (« Multiple top-level packages
discovered in a flat-layout: ['app', 'alembic'] »), setuptools refusant de
choisir entre `app/` et `alembic/` à la racine de `backend/`. Le chemin « sans
Docker » du README (`pip install -e .`) n'avait donc jamais été exercé tel
qu'écrit — seul le `Dockerfile`, qui installe les dépendances une à une sans
jamais installer le paquet local, avait été testé.

**Raison du correctif.** Ajout de
```toml
[tool.setuptools.packages.find]
include = ["app*"]
```
qui restreint la découverte au paquet `app` (et ses sous-paquets) et ignore
`alembic/` et `tests/` — ceux-ci n'ont jamais eu vocation à être installés
(`alembic` s'invoque en CLI via `alembic.ini`, `tests` est résolu par pytest
comme paquet-espace-de-noms implicite depuis la racine `backend/`, sans
`__init__.py`). Vérifié dans un venv propre, hors Docker : `pip install -e
".[dev]"` réussit, puis `alembic upgrade head`, le seeding et
`uvicorn app.main:app` fonctionnent tous par ce chemin, et la suite pytest
complète (64 tests) passe en l'utilisant.

## D15 — `product_mapping` inerte face à la résolution
*(OPEN DESIGN au moment de la rédaction ; **résolu en D18**, même journée —
voir D18 pour la conception retenue et sa vérification. Le constat ci-dessous
est conservé tel quel, comme trace du diagnostic qui a mené au correctif.)*

**Statut.** Contrairement aux entrées D1–D14, ceci n'est pas une décision de
conception prise et justifiée : c'est un vide qu'aucune décision n'a encore
comblé. Consigné ici pour qu'il reste visible tant qu'il n'est pas traité,
plutôt que découvert en production au premier branchement d'un vrai scraper.

**Constat.** `normalize_offers` (`backend/app/ingestion/normalize.py`)
résout chaque offre exclusivement via
`known_products.get(payload["product_external_key"])`. La table
`market.product_mapping`, l'endpoint `GET /api/ingredients/unmapped` (file
d'attente), `POST /api/ingredients/map`, et la colonne `confirmed_by` sont
tous fonctionnels pris isolément — ils écrivent et relisent correctement
leurs propres données — mais **aucun n'a d'effet sur la résolution d'une
offre**. Une confirmation manuelle n'est jamais reconsultée : une nouvelle
offre arrivant la semaine suivante avec le même `raw_text` retombe
`unmapped`, comme si elle n'avait jamais été traitée (vérifié en direct —
voir `CLAUDE.md`, section « État vérifié »).

**Le vide plus profond.** Même en branchant la lecture de `product_mapping`
dans `normalize_offers`, la table ne résout que jusqu'à un
`canonical_ingredient_id` — pas jusqu'à un `market.product`. Or la
contrainte de couverture du solveur a besoin d'un `v_p`
(`package_qty_in_base_unit`) précis pour convertir des unités achetées en
quantité d'ingrédient ; un ingrédient canonique seul ne suffit pas. Le
chemin réel est donc :

```
raw_text → product (v_p, marque) → canonical_ingredient
```

et non `raw_text → canonical_ingredient` directement. Une confirmation
manuelle devra donc pouvoir **créer un nouveau `market.product`** (nouveau
format, nouvelle marque) — ce n'est pas un cas limite en circulaire réelle,
c'est le cas normal : les formats d'emballage varient d'une semaine et d'une
bannière à l'autre bien plus souvent qu'ils ne se répètent à l'identique.

**Pourquoi ce n'est pas réglé ici.** Le jeu de seed JSON ne peut pas faire
apparaître ce problème : chaque `product_external_key` y est stable par
construction, fabriqué par `scripts/generate_seed.py` pour correspondre
exactement à un `market.product` existant. Concevoir correctement la
résolution `raw_text → product` exige de le faire contre de vraies données
scrapées — texte libre ambigu, formats hétérogènes d'une circulaire à
l'autre, nouveaux formats apparaissant sans prévenir — pas contre un JSON où
la question ne se pose pas par hypothèse. Toute conception faite maintenant,
sans ces données réelles sous les yeux, risquerait de figer une hypothèse
fausse. Volontairement laissé ouvert.

## D16 — Exclusion mutuelle des variantes d'échelle du même plat
*(corrigé lors d'une session de vérification, 2026-08-10)*

**Écart.** Le seed principal décline chacun de ses 20 plats en deux
recettes (`<id>` et `<id>_familial`), suivant une formule de mise à
l'échelle strictement uniforme sur les 20 paires : portions ×2, τ_fixe
×1,3, τ_marg ×0,8, â_fixe ×1,5, â_marg inchangé, β_r ×2, m_r +4. C'est une
économie d'échelle réaliste — deux segments d'une même courbe de coût non
linéaire pour produire un seul plat — et **ces variantes ne sont pas
modifiées** : le seed reste tel quel.

Mais rien dans le solveur ni dans le scoring ne savait que les deux
recettes d'une paire désignaient le même plat. Vérifié en direct sur le
plan de référence (seed principal, tous drapeaux actifs, profil canonique
R_min=4, α=0,3) avant correction : `chili_lentilles` (8 portions) et
`chili_lentilles_familial` (10 portions) étaient retenues **ensemble**,
chacune sous le plafond individuel x_r ≤ α·⌈D(1+ε)⌉ = 12,3, leur somme
(18) le dépassant de 46 % — un seul plat occupant 18 des 37 portions de la
semaine (49 %). Le compte de diversité Σδ_r ≥ R_min comptait 4 « recettes
distinctes » qui ne couvraient que 3 plats réels. La pénalité de
répétition inter-plans et la lassitude concave (`utility_segments`)
comparaient des `recipe.id` bruts : cuisiner `chili` une semaine puis
`chili_familial` la suivante n'était jamais vu comme une répétition.

**Correctifs.**

1. **`catalog.recipe.dish_family_id`** (migration `371e4b5dbcf8`, NOT NULL,
   indexée) — dérivé de la convention `<id>`/`<id>_familial`
   (`app/services/dish_family.py::dish_family_id_of`, utilisée à la fois par
   le backfill de migration et par `seed_catalog` à chaque seeding, pour
   qu'il n'existe qu'une seule implémentation de la convention). C'est une
   convention du **seed v1**, pas une sémantique générale : un futur
   catalogue réel devra fournir sa propre famille plutôt que s'appuyer sur
   un suffixe de nom.
2. **Exclusion mutuelle dans le solveur** — nouvelle contrainte dédiée
   `Σ_{r∈famille} δ_r ≤ 1` pour chaque famille de plus d'une variante
   (`solver/model.py::_add_variant_exclusion`), derrière
   `SolverConfig.enable_variant_exclusion` (**défaut `True`** — exception
   assumée au défaut « tout à False » des autres mécanismes : ce n'est pas
   un arbitrage coût/bénéfice à activer un à un, c'est une contrainte
   d'intégrité du modèle). Classée dans `flag_effects` côté
   `objectif_ou_contraintes_seulement` : elle ne touche jamais l'équation
   de couverture des ingrédients, seulement les contraintes sur δ_r.
   Conséquence vérifiée par test : une fois l'exclusion active,
   Σδ_r ≥ R_min ne peut plus être satisfaite en tirant deux variantes d'une
   même famille, donc R_min compte réellement des plats distincts, et le
   plafond de part n'est plus contournable par fractionnement entre
   variantes. Le rapport de diagnostic expose `distinct_dish_families`
   (distinct de `distinct_recipes`) et signale les contraintes d'exclusion
   saturées dans `saturated_constraints["diversite"]`.
3. **Pénalité de répétition et lassitude au niveau du plat**
   (`services/appetence.py::RuleBasedAppetenceScorer`) — la comparaison
   inter-plans se fait désormais sur `dish_family_id`, pas sur `recipe.id`
   (table de correspondance construite depuis `problem.recipes`, avec repli
   sur l'id brut pour un id historique absent du catalogue courant — dégrade
   vers l'ancien comportement plutôt que de planter). `utility_segments`
   hérite automatiquement de la correction puisqu'il calcule sa base via
   `score()` : aucun chemin résiduel où le premier segment d'une variante
   redémarrerait à plein tarif après que sa famille a été cuisinée la
   semaine précédente (vérifié par test,
   `test_repetition_penalty_applies_across_dish_family_variants`).

**Nouvelle décomposition du plan de référence (après correctif, seed
principal fraîchement réensemencé, profil canonique) :**

| recette retenue | portions |
|---|---:|
| `chili_lentilles_familial` | 12 |
| `galettes_lentilles_familial` | 9 |
| `riz_frit_oeuf_familial` | 8 |
| `saute_tofu_soja_familial` | 8 |

Total 37 portions, **4 recettes = 4 plats distincts** (`distinct_recipes`
== `distinct_dish_families` == 4, contre 4 recettes / 3 plats avant
correctif). Le solveur choisit systématiquement la variante familiale :
à ce niveau de portions par plat, l'économie d'échelle (τ_fixe à ×1,3 au
lieu de ×2, â_fixe à ×1,5) la rend strictement dominante sur la variante
régulière — plus besoin de fractionner un plat entre ses deux variantes
pour s'approcher du plafond de part, puisque chaque variante seule peut
maintenant absorber tout le volume que la contrainte de part autorise.

**Garde contre la dérive de `household_profile`.** En creusant, la base de
développement du conteneur courant avait `min_distinct_recipes = 7` alors
que `seed/main/household.json` déclare `4` (dérive constatée entre la
création de la ligne à 19:59 et sa dernière modification à 20:20, le
2026-08-10 — probablement une édition manuelle via l'écran Ménage pendant
le développement). Une fois la commande de garde écrite (ci-dessous) et
passée sur cette même base, la dérive s'est révélée plus large que
soupçonné : `time_value_cents_per_hour` (1500 → 1000), `diet_flags` (`[]` →
`['vegetarien']`), `taste_preferences` (préférences du seed remplacées par
d'autres) et `max_prep_time_per_meal_h` (1,5 → 2,5) divergent aussi. Nouvelle
commande
`python -m app.seeding.check_profile_drift [--seed-dir seed/main]`
(`app/seeding/check_profile_drift.py`) : compare `household_profile` en
base au seed versionné champ par champ, signale tout écart, sort en erreur
(code 1) si dérive détectée. **À exécuter en début de toute session de
vérification** (voir CLAUDE.md) — sans elle, une session peut tester
silencieusement contre un profil différent de celui documenté.

**`docs/calibration.md` a-t-il tourné avant ou après la dérive ?** Avant —
déterminable, pas seulement soupçonnable. Reproduit à l'identique (menu,
portions par recette, total) en réensemençant une base neuve depuis
`seed/main/household.json` intégralement (donc avec les cinq champs
canoniques ci-dessus, pas seulement `min_distinct_recipes`) ; la base
drifted du conteneur courant produit un menu différent (7 recettes,
39 portions, composition distincte — affecté par le cumul des cinq écarts,
pas seulement R_min). L'horodatage `updated_at` de la ligne en base (20:20)
postdate par ailleurs le fichier `docs/calibration.md` sur disque (19:21)
d'environ une heure. Les deux signaux concordent : la calibration
documentée reflète le profil canonique du seed, pas la base drifted. Aucune
revalidation nécessaire de ce chef.

**Note.** La dérive elle-même (`min_distinct_recipes = 7` dans la base de
développement du conteneur courant) n'a **pas** été corrigée par cette
session — seule la commande de garde a été ajoutée, conformément à la
consigne (comparer et signaler, pas corriger silencieusement un état de
base qui n'était pas dans le périmètre demandé). `python -m
app.seeding.check_profile_drift` continuera de la signaler tant qu'elle
n'aura pas été traitée explicitement (nouveau seeding, ou correction
manuelle assumée).

## D17 — Assertions 6 et 6b dédupliquées par `dish_family_id`
*(corrigé lors d'une session de vérification, 2026-08-10, en conséquence
directe de D16)*

**Écart.** Les assertions 6 et 6b (`services/validation.py`) raisonnaient
par **recette**, pas par **plat**, alors que D16 interdit à deux variantes
de la même famille d'être actives ensemble. Les deux souffraient d'un biais
symétrique :

- **Assertion 6** (borne basse) : `R_min · min(β_r)` utilisait le **minimum
  global** de β sur toutes les recettes survivantes, en supposant à tort
  que R_min recettes pouvaient toutes l'atteindre. Si ce minimum n'existe
  que dans une seule famille, les R_min−1 autres plats distincts requis ne
  peuvent pas tous l'égaler — l'ancienne formule passait alors à tort.
  Repéré concrètement : `n_repas = 2` sur le profil du seed principal
  (balayage de la session précédente) passait toutes les assertions puis
  échouait au solveur avec un simple statut `Infeasible`, sans message
  exploitable — exactement ce que la spec interdit (« lève une exception
  explicite, jamais un avertissement silencieux »).
- **Assertion 6b** (capacité, borne haute) : sommait `min(α·⌈D(1+ε)⌉, m_r)`
  sur **toutes** les recettes survivantes, comptant deux fois la capacité
  d'une famille à deux variantes alors qu'une seule peut être active à la
  fois (D16) — biais miroir, du côté optimiste cette fois (la capacité
  réelle est surestimée, pas sous-estimée).

**Correctif.** Les deux assertions comptent désormais **une seule valeur
par `dish_family_id`** parmi les recettes survivant au préfiltrage :

- Assertion 6 : pour chaque famille, le β minimal de ses variantes
  survivantes ; somme des R_min plus petites de ces valeurs, comparée à
  `⌈D⌉`. Ajout d'une vérification directe si moins de R_min familles
  distinctes survivent (infaisabilité immédiate, indépendante de β).
- Assertion 6b : pour chaque famille, la capacité la plus généreuse de ses
  variantes (`max` plutôt que la somme) ; somme sur les familles comparée à
  `⌈D(1+ε)⌉`.

Testé : reproduction du biais de l'assertion 6 avec un cas synthétique où
l'ancienne formule (`4×1=4 ≤ 37`) passait à tort alors que la vraie somme
minimale (`1+20+20+20=61`) est infaisable ; cas miroir pour 6b (double
comptage `5×8=40` vs le vrai `4×8=32`, sous R_min=4) ; cas « moins de
familles que R_min » ; et surtout le cas réel qui a motivé le correctif :
`n_repas=2` sur le profil du seed principal lève désormais
`DiversityInfeasibleError` avec un message lisible, sans jamais atteindre
le solveur (`tests/test_validation.py::test_assertion_6_catches_n_repas_2_on_seed_profile_before_solver`).

**Limite assumée.** `validate_problem` ne reçoit pas `SolverConfig` : la
déduplication par famille s'applique **inconditionnellement**, même si
`enable_variant_exclusion=False` est explicitement demandé. C'est cohérent
avec le statut de ce drapeau (D16 : exception au défaut « tout False »,
traité comme une contrainte d'intégrité du modèle plutôt qu'un mécanisme à
activer un à un) mais reste un couplage implicite non exprimé dans la
signature de la fonction — à garder en tête si `enable_variant_exclusion`
devient un jour un vrai choix utilisateur plutôt qu'un défaut de fait.
Conséquence concrète : deux tests de `tests/test_variant_exclusion.py`
écrits pour D16 (qui forçaient la combinaison de deux variantes via
`R_min=2` sur une famille unique) ont dû être repensés — ce cas précis est
désormais rejeté par l'assertion avant même d'atteindre le solveur, ce qui
est le comportement voulu. Les nouveaux tests démontrent le mécanisme réel
du contournement autrement : un choix économique (scinder la demande entre
deux variantes récolte deux fois le premier segment, plein tarif, de la
lassitude concave de l'appétence), pas une infaisabilité forcée par R_min.

**Oscillation régulier/familial à `n_repas` ∈ {11, 12, 13} : confirmée
réelle, pas un artefact de tolérance.** Le balayage de la session
précédente avait trouvé un format régulier (`galettes_lentilles`)
réapparaissant à `n_repas=12` entre deux points tout-familial (11 et 13),
et supposé qu'il s'agissait peut-être d'un quasi-ex-aequo à `mip_gap=0,01`.
Rejoué à `mip_gap=0` (optimalité certifiée, pas seulement une tolérance de
1 %) : **solutions et valeurs d'objectif strictement identiques** à celles
obtenues avec `mip_gap=0,01` (2523,22 ¢ / 2591,84 ¢ / 2621,05 ¢ pour
n=11/12/13). L'oscillation n'est donc pas un artefact numérique — c'est un
vrai optimum global qui bascule.

Piste de mécanisme (non vérifiée en détail, hors périmètre de cette
session) : à `n=12`, `galettes_lentilles` reçoit la plus petite allocation
des quatre plats retenus (6 portions) et c'est elle qui bascule en format
régulier ; mais à `n=11`, `saute_tofu_soja` reçoit une allocation encore
plus petite (4 portions) et **reste** familiale. Le seuil de bascule
régulier/familial n'est donc pas une quantité universelle — il dépend des
paramètres propres à chaque plat (τ_fixe de base plus faible pour
`saute_tofu_soja` que pour `galettes_lentilles`, donc le surcoût fixe du
format familial pèse proportionnellement moins pour lui, et son seuil de
bascule est plus bas). Chaque paire régulier/familial a vraisemblablement
son propre point de croisement économique ; le dériver précisément pour
les 20 paires n'a pas été fait ici.

## D18 — Résolution de D15 : `product_mapping` clé sur `(store_id, raw_text)`, résout vers `product_id`
*(corrigé lors d'une session de conception dédiée, 2026-08-10, à la demande
explicite de l'utilisateur — « démarrer D15 »)*

**Portée volontairement restreinte.** Comme D15 le mettait en garde, un
appariement flou/heuristique `raw_text → produit` (NLP, extraction
marque/format) exige de vraies données scrapées pour être conçu sans risquer
de figer une hypothèse fausse — **non traité ici**. Ce correctif ne touche
que la plomberie structurelle : rendre une confirmation manuelle réellement
effective. Restent hors périmètre, sciemment : appariement automatique,
écran de curation front-end dédié (aucun code front-end n'appelle les deux
endpoints de mapping aujourd'hui — vérifié), flux de rejet
(`MappingStatus.rejected`, jamais référencé dans le code).

**Trois défauts corrigés, pas un seul.**

1. **Le bug documenté par D15** : `normalize_offers` ne consultait jamais
   `product_mapping`.
2. **Un second bug, trouvé en lisant `routes.py::post_map`** : la route
   mettait à jour `staging.raw_offer.mapping_status` directement, sans
   jamais créer de ligne `market.price` — un raccourci contournant
   l'ingestion en lot (interdit par `CLAUDE.md` : « Chemin port → staging →
   normalisation, jamais de raccourci »).
3. **Un troisième défaut, relevé par l'utilisateur en revue du plan avant
   implémentation** : la clé `raw_text` seule suppose qu'un libellé
   identifie un produit *globalement*. Faux en circulaire réelle : un même
   libellé (« Poulet, format familial ») désigne des produits différents
   (marque, format, prix) d'une bannière à l'autre. Un mapping confirmé
   s'appliquerait silencieusement à la mauvaise offre chez une autre
   bannière.

**Schéma.** `market.product_mapping` (migration `9a2f6e1c4b7d`, chaînée
après `371e4b5dbcf8`) :
- supprime `canonical_ingredient_id` et la contrainte unique sur `raw_text`
  seul ;
- ajoute `store_id` (FK `market.store`, `NOT NULL`) et `product_id` (FK
  `market.product`, nullable) ;
- unique sur `(store_id, raw_text)`.

Le chemin réel devient `raw_text → product (marque, format) → ingrédient`,
jamais `raw_text → ingrédient` directement — une confirmation peut
**attacher un produit existant** ou **en créer un nouveau**, le cas normal
en circulaire réelle (formats/marques changent d'une semaine et d'une
bannière à l'autre).

**Garde de migration.** Aucune donnée de seed ne peuple jamais cette table
avec un mapping réel (vérifié par grep — le seed résout toujours via
`product_external_key`), donc pas de backfill : la migration supprime les
lignes existantes avant d'ajouter `store_id NOT NULL`. Mais avant de
supprimer, elle compte les lignes `confirmed_by IS NOT NULL` et **lève une
exception explicite** si ce compte est > 0 (une base de dev où quelqu'un
aurait confirmé des mappings à la main via l'ancienne API) — exactement le
travail que D15 existe pour protéger ; ne jamais le détruire silencieusement
au nom du correctif lui-même. Sur la base de test utilisée pour cette
session, le compte était 0 (aucun effet).

**Découverte en lisant `solver/model.py`, qui a changé la conception
retenue.** `ProductData.external_key` servait de composant de nom de
variable/contrainte PuLP (`f"n_{p.external_key}_{s.external_key}"`, etc.).
Un id synthétique (`manual-{id}`) pour les produits créés manuellement
aurait garanti l'unicité (traiter le symptôme) sans corriger le vrai
problème : coupler le solveur — un composant interne stable — à
`external_key`, un concept de couche d'ingestion que D15 qualifie lui-même
d'instable par nature. Correction retenue : le solveur nomme désormais ses
variables et contraintes depuis les clés de substitution (`p.id`, `s.id`,
uniques par construction PostgreSQL), jamais depuis `external_key`.
`external_key` reste utilisé uniquement là où c'est une règle métier
documentée — le tri du bris de symétrie lexicographique
(`docs/spec.md`) — jamais comme identifiant interne. `Product.external_key`
reste `NOT NULL` ; un produit créé manuellement reçoit toujours
`manual-{id}` après insertion, mais **comme convention d'ingestion**
(traçabilité, affichage), plus comme contrainte imposée par le solveur.
Confirmé sans régression : aucun test n'inspecte de nom de variable/
contrainte PuLP, et le rapport de diagnostic (`_saturated`) ne lit que les
préfixes `couverture_`/`plafond_arrets`/`diversite_r_min`/`part_max_`/
`exclusion_variante_`/`demande_` — jamais `lien_`/`sortie_`/`symetrie_`.

**`services/offer_resolution.py` (nouveau) — `OfferResolutionModule`.**
Même convention que `planning.py`/`household.py`/`catalog.py` : fonctions à
`session: Session` explicite, DTO dataclasses, exceptions typées
(`UnknownStoreError`, `UnknownProductError`,
`UnknownCanonicalIngredientError`). `attach_existing_product` et
`create_and_attach_product` upsertent `product_mapping` avec
`on_conflict_do_update` — **pas** `do_nothing` : un humain doit pouvoir
corriger une confirmation erronée. `do_nothing` reste réservé au seul upsert
automatique de `normalize_offers` à l'atterrissage, qui ne doit jamais
écraser une confirmation. **Ni l'une ni l'autre ne touche
`staging.raw_offer`** — correctif du deuxième bug ; c'est le prochain
passage en lot de `normalize_offers` qui reconsulte `product_mapping` et
résout les offres, historiques *et* futures, portant ce `(store_id,
raw_text)`. `ResolutionResult` porte `pending_offers` (compte en lecture
seule des offres `unmapped` en attente) pour que l'appelant sache combien
seront résolues au prochain passage, sans prétendre qu'elles le sont déjà.

**API.** `POST /api/ingredients/map` : nouveau corps
(`store_external_key`, `raw_text`, `confirmed_by`, et exactement un de
`product_id` ou `new_product`) — contrat changé intentionnellement, l'ancien
n'avait jamais d'effet réel. Après ce correctif, `api/routes.py` ne touche
plus SQLAlchemy/ORM nulle part (fermeture de la dernière exception laissée
par le refactor architectural précédent).

**Vérifié contre PostgreSQL réel** : cycle `alembic upgrade head` →
`downgrade -1` → `upgrade head` propre ; suite complète —
**86/86 tests passés, 0 sauté** (contre 82 avant ce chantier : +4 nouveaux
tests directs de `tests/test_offer_resolution_module.py` prouvant chacun
des trois défauts corrigés — dont le scénario exact décrit dans D15 comme
cassé, rejoué et confirmé résolu — plus `tests/test_api.py` mis à jour pour
le nouveau contrat). `tests/test_solver_toy.py`/`tests/test_solver_flags.py`
inchangés dans leurs assertions malgré le renommage des variables PuLP,
confirmant que c'est un pur changement de label.

## D19 — Sixième terme d'objectif : pénalité de gaspillage périssable
*(ajouté à la demande explicite de l'utilisateur, 2026-08-12, après une
discussion sur l'utilité réelle du terme de récupération une fois le
garde-manger retiré — voir CLAUDE.md pour le fil complet)*

**Écart assumé, explicite.** `docs/spec.md` (§ Fonction objectif) définit
$\min Z$ avec exactement cinq termes. Ce qui suit en ajoute un sixième —
une déviation délibérée de la formule exacte de la spec, pas une correction
de bug.

**Pourquoi un terme séparé, pas une transformation de σ_i.** `perishability`
est chargé (`IngredientData.perishability`) depuis le début de l'étape 4
mais n'était lu nulle part dans le solveur — un champ orphelin (déjà noté
dans « Évaluation franche », CLAUDE.md, avant même ce chantier). L'idée
naturelle — multiplier σ_i par un facteur dérivé de la périssabilité — a été
explorée et écartée pour deux raisons structurelles, pas un choix de
style :
1. Les ingrédients réellement périssables du seed principal ont **déjà**
   σ_i = 0 par calibration volontaire (`coriandre_fraiche`,
   `epinard_frais`, `scripts/generate_seed.py::SIGMA_TARGET_RATIO`) —
   n'importe quel facteur multiplicatif donne `0 × facteur = 0`, sans
   effet sur les ingrédients qu'on veut justement cibler.
2. `catalog.canonical_ingredient.salvage_value_cents_per_base_unit` porte
   `CHECK (>= 0)` (`salvage_nonneg`) — σ_i ne peut structurellement jamais
   devenir négatif, donc jamais représenter une pénalité par transformation
   de sa propre valeur.
3. Plus fondamentalement : le coût d'achat est déjà compté en entier au
   terme 1 (achats), qu'un ingrédient reste utilisé ou non. σ_i = 0 rend le
   solveur *indifférent* à un reste — ça ne le *pénalise* pas au-delà de ce
   qui est déjà payé. Une vraie pression de sélection exige un coût
   **additionnel**, jamais une réduction de crédit qui bute déjà sur zéro.

**Formule.** Par ingrédient : `pénalité_i = perishability_i · RATIO ·
prix_plancher_i`, où `prix_plancher_i = min_{p,s} c_ps(1+t_p)/v_p` —
réutilise `services/validation.py::min_taxed_price_per_base_unit` (déjà la
fonction de l'assertion 1), aucun nouveau calcul de prix. `RATIO`
(`solver/model.py::PERISHABLE_WASTE_PENALTY_RATIO`) est une constante
système, pas configurable par `SolverConfig`/le ménage — même famille que
l'ancien `MUST_USE_PANTRY_MIN_FRACTION` (« un bouton, pas un curseur »).

**Piège trouvé en implémentant, pas anticipé au plan.** Le premier jet
réutilisait `w_i`/`_add_surplus` (le mécanisme déjà existant du terme de
récupération), en changeant seulement le signe du coefficient dans
l'objectif. Testé en direct contre l'instance jouet (œuf forcé à
périssabilité 1,0) : **aucun effet** — le solveur mettait systématiquement
`w_i = 0`, quel que soit le surplus réel. Cause : `w_i ≤ approvisionnement −
besoin` ne fait que *plafonner* `w_i` ; avec un coefficient de pénalité
(positif, à minimiser), rien ne force `w_i` à refléter le vrai surplus — le
solveur le laisse simplement à sa borne basse (0), annulant toute pression.
Le mécanisme de crédit ne fonctionne que parce que l'objectif *maximise*
`w_i` (le pousse vers sa borne haute) ; une pénalité a besoin de l'inverse.

Corrigé avec une **variable et une contrainte séparées**, jamais un
partage avec `w_i` : `gaspillage_i ≥ approvisionnement − besoin`,
`gaspillage_i ≥ 0` (`solver/model.py::_add_perishable_waste`) — une
inégalité **miroir** de celle du terme 4, à dessein. Une borne *basse*
force `gaspillage_i` à refléter le vrai surplus ; la pression de
minimisation le sature naturellement vers le bas, sans jamais descendre
sous ce vrai surplus. Pas de risque de non-bornitude symétrique à
l'invariant existant (`w_i ≤ ..., jamais ≥`) : ici le coefficient est
positif (un coût, pas un crédit), donc gonfler `gaspillage_i` ne profite
jamais au solveur — le raisonnement inverse s'applique proprement.
`lowBound=0` couvre aussi le cas d'un ingrédient confirmé disponible
(`confirmed_available_ids`, `services/planning.py::finalize_plan`) où la
couverture n'est pas imposée : `approvisionnement − besoin` peut alors être
négatif, et `gaspillage_i` doit rester à 0, pas devenir un crédit caché.

**Calibration de `RATIO`, empirique, pas déduite.** Une valeur pensée par
analogie avec le plafond ≤ 0,8 de σ_i (donc ≤ 1) s'est révélée **sans aucun
effet** sur la sélection de recettes dans le même scénario jouet — le
gaspillage réel restait absorbé sans broncher, noyé sous les termes achats/
appétence (plusieurs centaines de cents). L'effet n'apparaît qu'à partir
d'un ratio ≈ 1, se stabilise dès 2 (`omelette_toy` passe de 1 à 3 portions,
le maximum que le surplus d'œufs peut absorber compte tenu de
`max_batch_servings`) et reste stable jusqu'à 20 sans dégénérer davantage.
`RATIO = 2,0` retenu : premier palier qui produit l'effet plein, pas juste
amorcé — vérifié par balayage direct contre le solveur, pas supposé.

**Portée volontairement restreinte** :
- Ne corrige pas l'honnêteté du crédit du terme 4 (σ_i·w_i) — `docs/
  spec.md` affirme que ce crédit n'est honnête que si `w_i` est reporté
  vers un stock réellement utilisable la semaine suivante ; ce report
  n'existe plus depuis le retrait du garde-manger (staples). Limite réelle,
  déjà documentée par la spec elle-même, mais indépendante de ce
  chantier : une pénalité n'a pas besoin d'une réalisation future pour
  être honnête (le coût est immédiat), contrairement à un crédit.
- `RATIO` non configurable, `docs/calibration.md` (balayage κ) non
  retouché — document historique déjà daté, non rejoué systématiquement à
  chaque changement du solveur (précédent déjà posé pour D16).

**Vérifié contre PostgreSQL réel** : aucune migration (aucune table
touchée, seulement le solveur et le reporting) ; suite complète —
voir CLAUDE.md pour le chiffre exact de cette tranche. `tsc -b`/
`vite build` propres.

## D20 — Le FCÉN entre dans un registre de candidats, jamais directement dans le canon

**Décision.** La publication bilingue FCÉN 2026 est importée hors requête HTTP
dans `staging.cnf_food_candidate`. La migration `f4a7c9d2e6b1` ajoute aussi
`catalog.canonical_ingredient_alias` pour les alias humains approuvés et
`catalog.canonical_ingredient_external_ref` pour les crosswalks versionnés.

**Raison.** Les 5 993 lignes du FCÉN sont des entrées de composition
nutritionnelle, pas 5 993 identités d'achat prêtes à employer. Elles ne
fournissent pas directement `unit_kind`, `base_unit`, `perishability`,
`salvage_value_cents_per_base_unit` ou `density_g_per_ml`. Un import direct
obligerait à inventer ces valeurs et
confondrait plats préparés, états cru/cuit et ingrédients achetables.

**Garanties de l'importeur.** `app.ingestion.cnf` lit l'archive ZIP officielle
avec un vrai lecteur CSV UTF-8 BOM, exige les descriptions primaires française
et anglaise, conserve le payload original, calcule le SHA-256 et upserte par
`(source_version, food_code)`. Les groupes 3, 19, 21, 22 et 25 reçoivent le
statut initial `excluded`; les boissons (14), `review`; les autres,
`candidate`. Ce classement est réversible et aucune ligne n'est supprimée.
Au rejeu, les champs source sont actualisés, mais `curation_status`,
`reviewed_by` et `reviewed_at` ne sont jamais écrasés.

**Limite volontaire.** Cette tranche pose la plomberie et l'import; elle ne
crée aucun ingrédient canonique, alias ou crosswalk automatiquement. La
promotion exige encore une décision de curation et le remplissage explicite
des champs métier du solveur.

**Vérification.** L'archive officielle observée le 12 août 2026 est lue en
entier : 5 993 lignes, dont 4 835 `candidate`, 284 `review` et 874 `excluded`,
avec l'empreinte publiée dans `docs/ingredient-database-research.md`. La suite
hors PostgreSQL passe (67 tests, 45 tests DB sautés faute de serveur local) et
la migration D19 compile en SQL PostgreSQL depuis la révision précédente.


## D21 — Les familles d'ingrédients décrivent la curation, jamais la substitution

**Décision.** La migration `b7e1d4a9c2f6` ajoute
`catalog.ingredient_family`, le lien nullable
`canonical_ingredient.family_id` et le journal append-only
`catalog.ingredient_curation_event`. Le flux hors ligne
`app.ingestion.ingredient_curation` offre trois décisions explicites :
attacher à un canon, créer une variante dans une famille ou exclure.

**Frontière architecturale.** Le flux vit dans `ingestion/` parce qu'il relie
`staging.cnf_food_candidate` au catalogue curé. Aucune route API et aucun
service du solveur ne lit `staging`. `family_id` n'est ajouté ni à
`ProblemData`, ni au préfiltrage, ni aux besoins : deux membres d'une même
famille restent deux identités non substituables.

**Dédoublonnage et audit.** Une collision sur l'id, le nom normalisé ou un
alias approuvé bloque une création et demande un rattachement. Les libellés
très proches sont signalés; créer malgré l'avertissement exige de citer les
ids acquittés dans le manifeste. Il n'existe aucune fusion automatique. Un
fingerprint rend le rejeu exact idempotent, tandis qu'une correction écrit un
nouvel événement avec auteur, justification, décision et instantané source.

**Démonstration riz.** Le seed crée la famille descriptive `riz` et y rattache
le canon existant (`riz_basmati` dans le seed principal, `riz` dans le jouet).
Le test de curation crée `riz_jasmin_test` comme deuxième identité de cette
famille et confirme que les produits restent liés au canon précis, jamais à
la famille. Les variantes réelles supplémentaires seront donc créées seulement
quand les recettes ou catalogues d'épicerie les justifieront.


## D22 — Le catalogue de départ contient des identités achetables, sans valeurs métier inventées

**Décision.** Le seed principal contient un socle curé de 1 026 ingrédients,
31 familles descriptives et 1 159 alias bilingues. Chaque entrée représente une
identité qu'un produit d'épicerie peut viser; les marques, formats, états de
préparation et plats composés n'y sont pas promus automatiquement.

**Valeurs incomplètes.** `perishability` et
`salvage_value_cents_per_base_unit` restent dans le modèle, mais deviennent
nullable. Les 23 ingrédients historiques du pilote conservent leurs valeurs
calibrées; les nouvelles identités du socle restent à `NULL` tant qu'elles ne
sont pas curées. Le solveur n'accorde aucun crédit de récupération en
l'absence d'une valeur. Les six densités déjà établies dans le projet sont
conservées; aucune densité par défaut n'est inventée.

**Reproductibilité.** `scripts/catalog_seed_data.py` est la source compacte du
socle manuel. `scripts/refine_cnf_catalog.py` applique au snapshot FCÉN 2026
un filtre versionné : groupes d'ingrédients seulement, identité bilingue,
état simple achetable, exclusion des formes cuites/assaisonnées/composées et
revue explicite de tout nom seulement similaire. Sur 5 993 lignes, 738 sont
promues : 591 créations et 147 rattachements exacts ou explicitement curés.
Les 333 créations similaires enregistrent les ids comparés comme acquittés;
11 mélanges ou fractions nutritionnelles revus restent exclus.
`scripts/generate_catalog.py` fusionne ces décisions et régénère ingrédients,
alias, crosswalks et événements d'audit. Les identifiants historiques utilisés
par les recettes, produits et essentiels sont tous préservés.


## D23 — Maxi et Super C sont capturés en parallèle, puis filtrés par le canon

**Décision.** Le lanceur démarre deux collecteurs indépendants dans un pool de
deux tâches. `MaxiBrowserExtractor` sélectionne explicitement le magasin 7552
dans un profil Edge persistant et séparé; `SuperCWebExtractor` sélectionne le
magasin public 640 et parcourt les rayons configurés. Chaque page devient une
capture JSON horodatée. L'import ne débute qu'après la réussite des deux
sources, puis emprunte le seul chemin permis : `RawOfferDTO` →
`staging.raw_offer` → normalisation → `market.price`.

**Frontière culinaire.** Les catégories par défaut excluent collations,
friandises, boissons et plats préparés. La catégorie reste toutefois un filtre
d'acquisition, jamais une preuve d'identité : seul un alias canonique non
ambigu et un format fixe autorisent l'import. Un produit composé, un snack ou
un article à poids variable demeure auditable dans le rapport sans entrer
dans le marché. Aucun poids moyen n'est inventé.

**Prix et charge.** Le prix courant, le prix régulier lorsqu'il est affiché et
le marqueur de promotion sont séparés. Un marqueur promotionnel reste vrai
même si le site omet le prix régulier. Le client espace ses requêtes de dix
secondes et applique une attente croissante sur HTTP 429. Les captures et
rapports sont locaux et rejouables; aucune collecte ne se produit dans une
requête API.

**Navigateur Maxi.** Le site Maxi refuse présentement le navigateur sans
interface. Le collecteur lance donc Edge en mode visible, avec un profil
d'automatisation distinct et une cadence lente. Il valide le cookie de magasin
avant d'accepter une page et conserve une capture d'écran diagnostique sur
échec. Une éventuelle vérification du site reste une intervention humaine; le
collecteur n'emploie aucun module de furtivité ni contournement.

**Reprise.** Une exécution utilise un dossier `run-*` propre. Le manifeste
`_complete.json` est écrit atomiquement seulement après la dernière page; la
reprise explicite sélectionne uniquement une exécution complète de la semaine.

## D24 — Le catalogue capturé s'importe sans rescraper, et une seule fabrique construit les adaptateurs

**Écart.** Deux points de la spec sont précisés ici, tous deux découverts en
branchant réellement le catalogue Super C sur le planificateur.

**1. L'import et la collecte sont deux gestes distincts.** `spec.md` décrit un
chemin unique port → `staging` → normalisation, ce qui reste vrai, mais la
seule façon de l'emprunter était `run_weekly_catalogues.py`, qui *capture puis*
importe. Une capture déjà sur disque ne pouvait donc pas atteindre
`market.product` sans relancer une collecte complète — Edge visible pour Maxi,
une requête toutes les dix secondes pour Super C. Conséquence mesurée : les
captures de la semaine étaient chiffrées par `quote_recipes.py` (2 165 produits,
129 recettes sur 161 avec un devis complet) sans jamais entrer en base, où le
solveur continuait de planifier sur les 83 produits de démonstration du seed.
Le filtre dur de préfiltrage « ingrédient sans aucun produit prixé » ne
laissait alors passer que **41 recettes sur 161, dont 40 étaient les recettes
de démonstration elles-mêmes** : l'application ne pouvait proposer que des
plats de démonstration, quelle que soit la richesse du catalogue de recettes
importées. `scripts/import_captured_catalogue.py` fournit le geste manquant.
Aucune écriture sans `--apply`.

**2. Un seul constructeur d'adaptateur.** Quatre appelants — collecte, devis,
audit de couverture, import Maxi — construisaient chacun leur adaptateur avec
sa propre copie des règles à passer. La correction précédente (voir `CLAUDE.md`,
revue de l'artefact de devis) avait aligné deux de ces copies et posé un test
qui *les comparait entre elles* ; la troisième et la quatrième restaient muettes,
et `scripts/import_maxi_catalogue.py` écrivait en base sans aucune des trois
règles de curation. `app.ingestion.catalogue_sources.CatalogueSources` est
désormais le seul constructeur, `tests/test_weekly_runner_wiring.py` interdit à
tout script d'en construire un directement, et `import_maxi_catalogue.py` est
retiré (couvert par `--banner maxi`). La période de circulaire jeudi-mercredi,
qui existait aussi en deux exemplaires, vit au même endroit.

**Ce que l'import a révélé, et qui n'est pas refermé.**

- **σ est une donnée de référence curée, bornée par un prix hebdomadaire.**
  L'assertion 1 exige σ_i ≤ 0,8·min prix taxé/unité, réévaluée à chaque
  résolution. σ du seed est dérivé des prix de *démonstration* : dès le premier
  import réel, σ(gousse_ail) = 5,28 ¢/gousse contre un plafond de 1,60 ¢, et
  **plus aucun plan ne pouvait être généré**. Les deux valeurs fautives
  (`gousse_ail`, `feuille_laurier`) sont recalibrées par la même formule sur le
  prix réellement observé (`scripts/generate_seed.py::REAL_PRICE_FLOOR_CENTS`).
  Le plancher de l'ail est cependant un **prix promotionnel** (48 ¢ les trois
  têtes, régulier 99 ¢) : une promotion plus profonde refera échouer
  l'assertion. Recalibrer σ à l'import ferait dépendre une donnée curée du
  marché hebdomadaire — décision produit, non prise ici.
- **Le domicile du profil et la bannière capturée ne sont pas dans la même
  ville.** Le profil de démonstration habite Montréal ; les seules bannières
  réellement capturées sont Maxi 7552 et Super C 640, à Québec. Magasin unique
  et règle « le plus proche du domicile » (D11) sélectionnaient donc un magasin
  de démonstration aux prix périmés, et le plan sortait `Infeasible` sans que
  rien ne nomme la cause. **Corrigé — voir D26** ; il reste que le domicile du
  profil ne décrit pas un vrai foyer, ce qui n'est corrigeable que par
  l'utilisateur (onglet Ménage).
- **Le catalogue branché ne suffit pas à changer le menu.** Les 121 recettes
  importées deviennent éligibles, mais elles portent `cuisines`/`categories`
  (pluriel, listes) là où `services/appetence.py` lit `cuisine`/`saison`
  (singulier) : elles restent toutes à l'appétence de base 1,30 $ quand une
  recette de démonstration atteint 2,15 $. Combiné au fait que le coût domine
  un crédit d'appétence plafonné à 2,65 $/portion, le solveur continue de
  choisir les plats les moins chers. Mesuré après import, magasin Super C
  imposé et `enable_batch_fixed_cost` actif : menu composé de chili aux
  lentilles, galettes de lentilles, riz frit et sauté de tofu, à 1,00 $/portion.

## D25 — Une recette dont le besoin est identiquement nul est écartée, jamais servie gratuitement

**Écart.** `enable_batch_fixed_cost` est le seul drapeau qui altère l'équation
de besoin (`solver/model.py::FLAGS_ALTERING_NEEDS`) : désactivé, il retire la
composante fixe par lot des besoins. La spec traite ce drapeau comme un
mécanisme de coût que l'on active progressivement. Or les 121 recettes
importées ont **toutes** leurs quantités dans cette composante — une recette
scrapée décrit un lot, pas une portion. Drapeau éteint, leur besoin est donc
identiquement nul : le solveur les sert **gratuitement**, et comme rien ne
coûte moins que zéro, il en remplit tout le menu. Vérifié en direct après
l'import : menu de trempette ranch, popcorn, frites d'avocats et boulettes
teriyaki, tous les termes de l'objectif à 0,00 $, liste d'épicerie vide.

**Décision.** Le préfiltrage écarte une recette dont toutes les quantités
marginales sont nulles quand `enable_batch_fixed_cost` est éteint, et l'inscrit
au rapport de diagnostic sous l'étape `besoin_non_nul`. Ce n'est pas un filtre
de préférence : sous ce drapeau, une telle recette est mal modélisée, pas
gratuite. Le module de prix tenait déjà exactement cette position
(`recipe_costing.py::RecipeNotScalableError` — « les rescaler proportionnellement
inventerait une donnée que la source ne publie pas »). Le préfiltrage cesse
d'être plus laxiste que l'affichage du prix.

**Conséquence à assumer.** Avec le défaut de configuration actuel du front-end
(`DEV_DEFAULT`, tous les drapeaux à `False`), ce filtre ramène le problème aux
40 recettes de démonstration : les recettes importées ne sont atteignables
qu'avec `enable_batch_fixed_cost` actif. Le défaut du front-end est un défaut de
développement, pas un défaut de produit.

## D26 — Le magasin retenu doit pouvoir approvisionner, et l'assertion 4 se juge sur lui

**Écart.** Deux règles de la spec se contredisaient en silence dès qu'un vrai
catalogue est arrivé à côté du catalogue de démonstration.

D11 fixe, en magasin unique, « le plus proche du domicile ». L'assertion 4
vérifie que chaque ingrédient requis a « un produit avec prix valide ». Mais
elle balayait **tous** les magasins pendant que le modèle n'autorisait des
achats que dans **un**. Les deux passaient donc, et le problème était pourtant
infaisable.

Constaté en direct sur l'application, domicile de démonstration à Montréal,
catalogue Super C importé :

| magasin | distance | prix valides au 19 août |
|---|---:|---:|
| `epicier_du_coin` | 0,7 km | **0** |
| `marche_central` | 2,1 km | 0 |
| `superc_640` | 225,1 km | **2 165** |

La règle retenait `epicier_du_coin`, aucun achat n'était possible, et
l'utilisateur recevait : « Infaisable (Infeasible). IIS indisponible avec CBC ;
toutes les assertions pré-solveur sont passées — l'infaisabilité vient de
l'interaction des contraintes actives, **en dernier lieu du drapeau
`enable_variant_exclusion`** ». Le drapeau accusé n'avait aucun rapport : c'est
simplement le dernier de la liste, faute de mieux à nommer.

**Décision, en deux moitiés.**

1. `solver/model.py::select_stores` — extraite en fonction pure, appelée une
   fois par résolution et passée à la fois à `validate_problem` et à `_Ctx`
   (les deux doivent juger le même ensemble). La règle D11 n'est pas remplacée,
   elle est **restreinte aux magasins qui ont au moins un prix valide à la date
   du plan** : un magasin sans circulaire chargée n'est pas un candidat. À prix
   égal de disponibilité, le plus proche gagne toujours — le choix du magasin
   reste géographique, l'arbitrage de prix appartient au solveur. Si aucun
   magasin n'a de prix, on retombe sur le plus proche et l'assertion 5 nomme le
   catalogue périmé.
2. `min_taxed_price_per_base_unit` accepte un `store_ids` optionnel, et
   l'assertion 4 s'y restreint. Le message nomme désormais le magasin et la
   date. L'assertion 1 et le préfiltrage gardent le balayage global : borner σ
   par le prix le plus bas du marché est la borne la plus stricte, et le
   préfiltrage est une réduction grossière qui tourne avant toute sélection.

**Effet mesuré.** Configuration par défaut de l'application, aucun drapeau,
19 août : `Infeasible` → **`Optimal`**, magasin `superc_640`, 25,32 $. Un
magasin imposé sans prix ne rend plus une infaisabilité muette mais un 422 :
« Aucun produit avec prix valide au 2026-08-19 au magasin epicier_du_coin
pour : [...] ». Garde : `tests/test_store_selection.py`.

## D27 — Plancher de dépense d'épicerie : le budget se raisonne en dollars, pas en points d'appétence

**Écart.** La spec n'a qu'un levier contre le menu le moins cher : le plancher
d'appétence (`appetence_u_min_dollars`, mode « constraint »). Il fonctionne,
mais il répond « quel menu », pas « quel montant ». Mesuré sur `seed/main`,
semaine du 13 août 2026 :

| U_min | panier | menu |
|---:|---:|---|
| 50 | 32,07 $ | riz frit, crêpes, chili aux lentilles, galettes, omelette |
| 70 | 62,77 $ | tacos au bœuf, tacos au tofu, chili con carne, dahl… 10 plats |
| 90 | infaisable | plafond d'appétence du catalogue |

Un ménage qui veut employer son budget parle en dollars. La correspondance
points → dollars, elle, change à chaque circulaire : 70 valaient 62,77 $ cette
semaine-là et rien ne le garantit la suivante.

**Décision.** `min_grocery_spend_cents_cad` rejoint les paramètres
surchargeables du profil (K, R_min, α, ε, U_min), résolu par
`services/params.py` comme les autres. La contrainte
`solver/model.py::_add_min_spend_constraint` porte sur **la même expression**
que le terme d'achats de l'objectif — pas un recalcul parallèle : avec
`enable_staples`, le prix vu par le solveur pour un essentiel est biaisé vers le
plus bas historique, et deux expressions distinctes se croiraient d'accord en
divergeant de plusieurs dollars.

**Assertion 0 — la garde qui rend le mécanisme honnête.** Un plancher de
dépense n'achète un meilleur menu que si quelque chose récompense un meilleur
menu. L'appétence en crédit dans l'objectif joue ce rôle : parmi tous les
paniers atteignant le montant, le solveur retient le plus appétissant. En mode
« constraint », l'appétence quitte l'objectif pour devenir une borne — plus rien
ne départage les façons de dépenser, et le chemin le moins cher vers le montant
devient le surplus. `validate_problem` refuse donc explicitement la combinaison
plancher de dépense + mode « constraint » (`SpendFloorWithoutRewardError`).
Numérotée 0 parce qu'elle ne lit aucune donnée, seulement les paramètres
résolus : elle passe avant les six assertions de la spec, et son échec nomme un
réglage à corriger plutôt qu'un catalogue à rafraîchir.

**Limite mesurée, pas supposée.** J'attendais qu'un plancher démesuré soit
infaisable. Il ne l'est pas : rien ne borne la quantité achetée par le haut (la
couverture est approvisionnement ≥ besoin), donc le solveur atteint n'importe
quel montant en achetant plus. Ce qui sature, c'est l'appétence. Part de la
quantité achetée qui n'est pas consommée par le menu, `seed/main`, même semaine :

| plancher | achats | appétence | quantité non consommée |
|---:|---:|---:|---:|
| aucun | 35,06 $ | 54,50 | 19,4 % (formats d'emballage, incompressible) |
| 60 $ | 60,05 $ | 67,30 | 28,6 % |
| 90 $ | 90,03 $ | 71,40 | 32,2 % |
| 200 $ | 200,02 $ | 70,40 | 69,0 % |
| 600 $ | 600,29 $ | 71,40 | 88,8 % |

Le mécanisme est donc un budget **dans sa plage utile** — jusqu'à ce que
l'appétence plafonne — et du gaspillage au-delà. Ce n'est pas verrouillé par
une borne arbitraire : la valeur utile dépend du catalogue de la semaine et du
nombre de portions, et une borne codée en dur mentirait aussi souvent qu'elle
protégerait. Ce qui **est** verrouillé, c'est la mesure :
`tests/test_min_grocery_spend.py` tient la saturation de l'appétence, pour que
personne ne présente plus tard ce plancher comme un budget sans plage.

**Précision d'argent.** Le plancher est imposé sur l'expression PuLP, en
flottants ; le montant rapporté est recalculé en `Decimal` depuis la solution
entière (INVARIANTS). Les deux divergent de moins d'un cent — mesuré 5 999,42
contre un plancher de 6 000 sur le catalogue Super C réel. Les tests tolèrent un
cent ; affirmer l'égalité stricte serait faux.

## D28 — Rafraîchir les prix depuis l'application : un lot lancé, jamais attendu

**Tension.** `ports/circular.py` et D23 posent que la collecte est exécutée
**en lot**, « jamais dans le chemin d'une requête HTTP », et que « aucune
collecte ne se produit dans une requête API ». Or l'usager qui voit « le
catalogue de prix est périmé » — le cas dès le jeudi suivant, la circulaire
Super C couvrant jeudi-mercredi — n'avait aucun geste depuis l'application. Il
devait connaître `scripts/run_weekly_catalogues.py`. Un bouton ne peut pas non
plus *attendre* : une passe Super C complète demande une trentaine de minutes
(173 pages à une requête toutes les 10 à 12 secondes, plus la grille des
promotions).

**Décision.** `services/price_refresh.py` **démarre un processus détaché** et
rend la main. `POST /api/price-refresh` répond **202** — rien n'est fait au
retour, un lot vient d'être accepté — et `GET /api/price-refresh` rapporte
l'état. L'invariant tient au sens propre : aucune requête HTTP ne collecte, et
le module de lancement n'importe aucun adaptateur web ni aucune bibliothèque
réseau. La garde est structurelle, sur les imports du module
(`tests/test_price_refresh.py`), parce qu'un `httpx.get` ajouté un jour
passerait tous les tests fonctionnels tout en violant l'invariant.

**Deux processus, pas un.** L'API démarre un *superviseur*
(`python -m app.services.price_refresh --run superc`) qui lance le collecteur,
attend sa fin et écrit l'état terminal. Sans lui personne ne lirait le code de
sortie : l'API redémarre à chaque édition de fichier sous `--reload`, et une
collecte réussie serait alors indistinguable d'un plantage. L'état vit dans un
fichier JSON, jamais en mémoire, pour la même raison.

**Ce qui est délibérément absent.**

- **Maxi.** Son collecteur exige une fenêtre Edge *visible* et parfois une
  vérification humaine. Lancé depuis un processus serveur, il ouvrirait une
  fenêtre que personne ne regarde et échouerait après de longues minutes. La
  bannière est refusée en 422 avec cette raison, plutôt que tentée.
- **Aucune file d'attente.** Une seconde demande est refusée en 409. Deux
  collectes en parallèle doubleraient la cadence vue par le détaillant, ce que
  le limiteur du collecteur existe précisément pour éviter.
- **Aucune progression fabriquée.** L'écran affiche la fin du journal du
  collecteur — sa propre sortie, page par page. Un pourcentage calculé à côté
  ferait deux vérités dont une fausse.
- **Aucune annulation.** Un clic malencontreux lance trente minutes de collecte
  qu'aucun écran ne peut arrêter. Le bouton se débloque seul (un état `running`
  dont le processus a disparu est rapporté `failed`), mais arrêter une collecte
  en cours reste un geste de ligne de commande. À faire si le besoin se
  présente ; l'inventer maintenant serait une commande d'arrêt non éprouvée sur
  un processus détaché.

**Deux défauts trouvés en exécutant, pas en relisant.**

1. `os.kill(pid, 0)` — le sondage de processus habituel sous POSIX — est
   traduit par CPython sous Windows en `TerminateProcess(handle, 0)`. Le
   sondage aurait **tué** la collecte, et avec un code de sortie 0, donc en la
   faisant passer pour réussie. Remplacé par `OpenProcess`/`WaitForSingleObject`
   via `ctypes`, avec son test.
2. Le journal s'affichait en mojibake (« [D�marrage] Superc en parall�le ») :
   un enfant Python écrit sous Windows dans la page de codes de la console, pas
   en UTF-8. Le collecteur parle français à chaque ligne et ce journal est la
   seule fenêtre de l'usager sur une tâche de trente minutes.
   `PYTHONIOENCODING`/`PYTHONUTF8` sont désormais imposés à l'enfant.

### D28 (suite) — Le bouton met la base à jour, même sur une capture tronquée

**Constat qui a forcé la reprise.** Le bouton lançait
`run_weekly_catalogues.py --apply`. Or ce script refuse d'importer dès qu'un
rayon est tronqué :

```python
if incomplete_listings:
    raise RuntimeError("Capture Super C tronquée sur N rayon(s) : …")
```

L'exception est levée **avant** le bloc `if args.apply:`. Mesuré le 20 août
2026 : 17 rayons sur 35 paginaient moins de produits que Super C n'en annonçait
(250 légumes annoncés 324, 317 pâtes-riz-féves annoncés 398). La passe
s'arrêtait donc sans écrire une seule ligne, et le bouton ne servait à rien les
semaines où le site pagine court — c'est-à-dire celle-là.

**Décision : deux phases, et la règle du collecteur reste intacte.** Effacer le
refus aurait supprimé une garde délibérée (« l'écart est retenu et rejeté après
coup, jamais avalé ») pour tous les appelants, ligne de commande comprise. Le
superviseur enchaîne donc :

1. **collecte** — `run_weekly_catalogues.py` **sans** `--apply`. Il capture, et
   ne met à jour `data/catalogue-registry/` que si la passe est complète, comme
   avant. Son échec est retenu, pas fatal.
2. **import** — `import_captured_catalogue.py --apply`, qui lit les dossiers de
   capture de la semaine sans se soucier de leur complétude.

C'est l'import qui décide de l'état, parce que c'est lui qui écrit. Une collecte
tronquée suivie d'un import réussi donne donc `succeeded` **et**
`collection_complete: false` : deux faits distincts, que l'écran présente
distinctement (« Prix mis à jour — capture partielle »). Les confondre ferait
croire à un catalogue entier ; les taire ferait croire à un échec.

**Vérifié en exécutant.** Phase 2 lancée sur les captures partielles du 20 août :
1 545 produits et 5 966 prix écrits, nouvelle fenêtre de validité
2026-08-20 → 2026-08-26, `market.product` de 2 248 à 2 267. La date du jour est
passée de « non couverte » à 1 545 prix valides.

**Ce que les chiffres de l'écran ne sont pas.** « N produits, N prix écrits en
base » est lu du rapport d'import, jamais estimé — et `prices_upserted` compte
les upserts de toutes les fenêtres re-normalisées, pas les prix de la semaine
courante. Le nombre de lignes de la semaine se lit dans `market.price`.

### D28 (suite) — « Quand a-t-on scrapé » se lit sur le disque, pas dans l'état du bouton

**Manque.** L'écran ne montrait la date d'une collecte que pendant et après un
lancement *passé par l'application*, et seulement pour le dernier. Un usager qui
lance `run_catalogues.cmd` — le raccourci livré dans le dépôt, prévu pour être
double-cliqué — se serait vu répondre « jamais collecté » juste après une passe
complète. Et à l'état `idle`, l'écran ne disait rien du tout : impossible de
savoir si les prix affichés datent de deux heures ou de trois semaines.

**Décision.** `capture_layout.last_capture_at()` lit l'horodatage du **nom des
dossiers d'exécution** (`run-<AAAAMMJJ>T<HHMMSS>Z`), que le collecteur écrit
lui-même avant sa première page. C'est la seule trace qui existe quel que soit
le chemin de lancement, et elle ne dépend d'aucun état applicatif. La ligne est
donc toujours affichée, même quand le bouton n'a jamais servi : « Dernière
collecte Super C : 20 août à 08 h 56 — il y a 2 h ».

Choix explicites :

- **L'instant de départ, pas celui de la fin.** C'est ce que le nom du dossier
  porte, et une passe dure au plus une heure. Une passe tronquée compte donc
  aussi : la question posée est « quand a-t-on scrapé », pas « quand a-t-on
  réussi » — deux faits que l'écran garde séparés, le verdict de la dernière
  mise à jour vivant dans son propre panneau.
- **Un nom malformé n'est jamais une date inventée** : il est ignoré.
- **Les dispositions anciennes à dossiers plats** (sans dossier d'exécution) ne
  portent aucun horodatage dans leur nom et ne sont pas vues. Dit ici plutôt que
  deviné par un `mtime`, qu'une simple copie de fichiers falsifierait.
- **`market.price` n'a pas d'horodatage** et `market.product.updated_at` ne
  bouge que sur une *insertion* (l'upsert brut ne déclenche pas le `onupdate` de
  l'ORM). Ni l'un ni l'autre ne pouvait répondre « quand la base a-t-elle été
  écrite » — mesuré avant de choisir. La fraîcheur affichée est donc celle de la
  **collecte**, ce que la question posait.

**Défaut d'affichage assumé.** Le panneau de verdict garde le résultat de la
dernière mise à jour, et rien ne le corrige si la base est écrite par un autre
chemin (un import lancé à la main, par exemple). On peut donc lire « La mise à
jour a échoué » devant une base parfaitement à jour — constaté. La ligne de
fraîcheur et la fenêtre de prix chargés, toutes deux lues des données, disent
alors la vérité à côté.

### D28 (suite) — Un verdict de mise à jour est une nouvelle, pas un statut

**Constat rapporté deux fois par l'usager.** « La mise à jour a échoué —
démarrée à 08 h 56 (code 1) », avec sa liste de rayons tronqués, restait affiché
des heures après, devant une base parfaitement à jour — écrite entre-temps par
un import lancé à la main. Le verdict n'était pas faux : cette passe avait bien
échoué. C'est sa **pertinence** qui avait expiré, et sa présentation qui le
faisait lire comme une affirmation sur l'état courant du catalogue.

**Décision.** `DELETE /api/price-refresh` efface le verdict — pas son journal,
qui reste la trace de ce qui s'est passé. Un bouton « Masquer » dans l'encadré,
refusé (409) si une mise à jour est en cours : il n'y a alors pas encore de
verdict. Le libellé passe de « La mise à jour a échoué » à « Dernière tentative :
échec », qui dit ce que la phrase décrit — un lancement passé.

**Écarté : l'expiration automatique.** Masquer un verdict au bout de N heures
aurait choisi un délai arbitraire, alors que le moment où la nouvelle cesse
d'être utile n'appartient qu'à celui qui l'a lue. Écarté aussi : deviner que la
base a été écrite ailleurs pour taire le verdict — `market.price` n'a aucun
horodatage (voir plus haut), donc la comparaison serait fondée sur rien.

**Ce que l'écran distingue désormais**, trois faits de trois sources
différentes, aucun déduit d'un autre : la fenêtre de prix chargés (la base), la
date de la dernière collecte (les dossiers de capture), et le verdict de la
dernière tentative (l'état du lanceur, effaçable).

## D29 — Un apport négligeable est une déclaration bornée, et le plafond n'est pas décoratif

**Contexte.** Le calcul nutritionnel refuse tout total dont une ligne
d'ingrédient n'est pas résolue. Appliqué tel quel au corpus, ce refus est
définitif pour 160 recettes sur 161 : le sel, l'eau, le bouillon et les épices
n'ont pas d'aliment FCÉN rattaché et n'en auront pas avant plusieurs sessions de
curation. Il fallait pouvoir déclarer qu'un apport est négligeable sans que
« négligeable » devienne un synonyme d'« oublié ».

**Décision.** `config/nutrition-rules.json`, versionné, lu par un seul module
(`services/nutrition_rules.py`). Chaque entrée déclare la **teneur fédérale
mesurée** (`kcal_per_100g`, avec le code d'aliment FCÉN en provenance), le
**plafond de quantité** sur lequel la déclaration porte, et le plafond de masse
par unité de base. La borne d'erreur en découle — elle n'est jamais saisie à la
main — et le module la somme par recette
(`kcal_error_bound_per_serving`), que l'écran affiche en « ± ». Une entrée sans
teneur mesurée est refusée à la lecture : sans elle, la règle ne serait qu'une
omission qui s'ignore.

**Le plafond de quantité est le cœur de la règle, pas un ornement.** Une
déclaration porte sur un assaisonnement, pas sur un aliment. Mesuré dans ce
corpus : `basilic_frais` pèse 187,5 g **par portion** dans
`bon_pour_toi_salade_aux_peches_facon_panzanella` (375 g pour deux portions, à
côté de 2 000 g de roquette et 900 g de pêches — une conversion
millilitre→gramme fautive à l'import, pas une recette). Au plafond, la
déclaration se retire et l'ingrédient redevient bloquant : la donnée fautive
remonte au lieu d'être absorbée par une borne de 0 kcal. Cinq ingrédients y
tombent réellement (`epices_steak_montreal` 11,25 g/portion,
`epices_italiennes` 5 g, `assaisonnement_chili`, `moutarde_seche`,
`origan_seche` 3,75 g), et c'est le comportement voulu.

**La règle est un recours, jamais une surcharge.** Un ingrédient déclaré
négligeable qui porte tout de même un aliment FCÉN et une quantité convertible
est calculé pour de vrai. Sans cette précédence, les 19 épices déjà appariées du
corpus auraient perdu leur chiffre au profit d'une borne, et le même fait aurait
eu deux lecteurs — le motif qui a déjà coûté deux divergences à ce dépôt.
L'entrée par ingrédient l'emporte sur celle de sa famille (le sel est une épice
au sens du canon, mais sa borne est 0 kcal jusqu'à 15 g, là où la famille
s'arrête à 2,5 g d'une épice moulue quelconque).

**Écarté : une borne par famille sans plafond de quantité.** Elle aurait dû
tenir pour la pire épice à la pire quantité observée — 525 kcal/100 g
(FCÉN 193, muscade) × 11,25 g = 59 kcal par portion, ce qui n'est pas
négligeable et rendrait la déclaration fausse. Écarté aussi : ne déclarer que
des ingrédients nommés, sans famille. Les 19 épices non appariées auraient exigé
19 entrées mesurées une à une pour un apport que le plafond borne déjà.


## D30 — L'aliment FCÉN retenu pour la nutrition se déclare, il ne se devine pas

**Constat mesuré.** Le pont canonique → FCÉN a été curé pour l'**identité
commerciale**, et il ne suffit pas pour la nutrition :

- **26 ingrédients portent plusieurs aliments FCÉN** (la contrainte d'unicité
  porte sur le code fédéral, pas sur l'ingrédient). L'avocat en porte trois —
  1511 toutes variétés (160 kcal/100 g), 1512 Californie (167), 1513 Floride
  (120). Un écart de 39 % ne s'arbitre pas par un tri.
- **Certains rattachements nomment une autre classe d'aliment.** `mais` a été
  **créé** (`create_variant`) depuis l'aliment 4452 « Pâtes, maïs, sèches »,
  357 kcal/100 g au lieu de 86 pour du maïs. Le nom se ressemble; l'aliment
  non. La curation de prix pouvait vivre avec l'approximation, un calcul
  nutritionnel non.

**Décision.** Le bloc `food_choices` du même fichier de règles. Chaque entrée
nomme l'ingrédient, le code d'aliment retenu, un `kind` et une justification
écrite obligatoire : `primary` (l'ingrédient porte plusieurs aliments, celui-ci
est le bon — et le module refuse un `primary` qui désigne un aliment non
rattaché), `correction` (les aliments rattachés nomment une autre classe),
`substitution` (le FCÉN ne publie pas cette variété; un générique
nutritionnellement équivalent la remplace). À défaut de choix déclaré : un seul
aliment rattaché est retenu tel quel, plusieurs donnent un refus
`ambiguous_cnf_food` qui cite les codes.

**Pourquoi pas corriger le seed.** Les références FCÉN de `seed/main` sont
**générées** depuis les décisions de `seed/main/cnf_catalog_curation.json` par
`scripts/generate_catalog.py`, et le journal d'événements de curation est
append-only. Retirer deux décisions sur trois pour l'avocat réécrirait
l'histoire d'une décision humaine passée. Le règlement, lui, ajoute une décision
datée et motivée sans effacer les précédentes — et c'est aussi la forme que
prendront les substitutions déclarées (basmati, dijon), qui n'ont aucun aliment
FCÉN à rattacher.

**Ce que l'audit publie plutôt que de trancher.** La carte des appariements
réellement utilisés (nom canonique, nom fédéral, énergie, nombre de recettes
touchées), pour relecture humaine, et à part les désaccords francs — aucun mot
commun entre les deux noms. Un contrôle sur le seul premier segment du nom
fédéral a été essayé puis retiré : il signalait 30 appariements dont 25 justes
(« Épices, aneth, frais » pour « Aneth frais » — le premier segment fédéral est
souvent une classe, pas un démenti). Distinguer une classe d'un produit dérivé
demande les règles d'appariement, qui sont un chantier à part; un signal à 83 %
de faux positifs apprend surtout à ignorer la colonne.


## D31 — Le calcul nutritionnel lit `staging`, et n'y écrit jamais

**Contexte.** Les teneurs fédérales vivent dans `staging.cnf_nutrient_amount`,
et la règle d'architecture dit que les services ne lisent jamais `staging`.

**Décision.** La façade `services/recipe_nutrition_facts.py` les lit, en
lecture seule, sous les deux mêmes conditions que `services/offer_resolution.py`
— qui lit déjà `staging.raw_offer` pour alimenter sa file de revue : ne jamais
écrire, et ne jamais court-circuiter la normalisation. L'invariant réel que la
règle protège est celui-là. La copie FCÉN n'est d'ailleurs pas une file
transitoire : elle est versionnée par `source_version` et scellée par
`archive_sha256`, donc rejouable à l'identique.

**Écarté : une table `catalog` de teneurs alimentée par normalisation.** C'est
la forme architecturalement pure, et elle reste ouverte. Elle coûte une
migration et une étape de normalisation pour recopier une donnée fédérale déjà
versionnée, sans rien ajouter à ce que le calcul en fait aujourd'hui.

**Corollaire nommé plutôt que silencieux.** Une base sans teneurs importées ne
rend pas « 0 kcal » ni 309 ingrédients « sans donnée » : la façade lève
`NutritionDataUnavailable`, qui devient un 503 citant la commande d'import.
C'est une panne de déploiement, pas un chantier de curation — la distinction
qu'un compteur à zéro effaçait.


## D32 — L'appariement canonique → FCÉN se propose par jetons, et se rejette par motif

**Pourquoi pas la similarité de chaînes déjà en place.**
`normalize_label`/`label_similarity` compare des chaînes entières. Mesuré sur
l'archive réelle, ce choix manque les appariements dont le nom fédéral commence
ailleurs — « Ketchup » contre « Tomates, ketchup (catsup) », « Parmesan » contre
« Fromage parmesan, pâte dure », « Courgette » contre « Courge d'été, courgette
(zucchini), crue », « Poireau » contre « Poireaux (bulbe et portion inférieure),
crus » — et accepte des faux positifs où le mot est présent mais l'aliment n'a
rien à voir. La recherche par jetons retrouve les premiers; deux rejets francs
écartent les seconds.

**Les deux rejets.** `cooked_or_prepared_form` : le candidat porte une marque de
cuisson que le nom canonique ne porte pas (par 100 g, une carotte bouillie n'est
pas une carotte crue). `composite_dish` : aucun mot du canon n'apparaît dans les
deux premiers segments du nom fédéral — le FCÉN nomme du général au particulier,
donc un ingrédient cité au troisième segment est un ingrédient *de* la
préparation nommée devant (« Pomme de terre, frite, congelée, préparée au
restaurant avec de l'huile végétale » pour de l'huile). Les rejets sont publiés
avec leur motif, jamais effacés.

**Quatre défauts trouvés en exécutant sur l'archive, pas en relisant.** Ils sont
tous consignés en test, parce qu'aucun n'était visible en lisant le code :

1. **La ligature « œ »** ne se décompose pas en Unicode. « Œuf de calibre gros »
   ne partageait donc aucun jeton avec « Oeuf, poule, … » et s'appariait sur le
   mot « gros » à « Porc, morceau de gros, gras de dos, cru » — 812 kcal/100 g.
2. **Les marques de cuisson comparées par préfixe.** « Poulet **à griller** »
   est une catégorie d'oiseau, pas du poulet grillé : le seul poulet cru en
   cuisse du fichier fédéral était rejeté. « Cuisse » se lisait comme « cuit »
   par le même mécanisme. Les marques se comparent désormais au mot entier,
   fléchi.
3. **La congélation lue comme une cuisson.** Le FCÉN écrit « Oeuf, poule,
   entier, frais ou congelé, cru » : c'est un état d'achat. Le traiter en
   préparation rejetait l'œuf de poule et laissait l'œuf de cane en tête.
4. **Le seuil de trois lettres.** « riz », « ail », « sel », « eau », « jus »
   sont des aliments. Un seuil à quatre lettres laissait `riz_arborio` et
   `riz_non_precise` sans aucun candidat, faute de pouvoir chercher « riz ».

**Ce que le classement encode, et ce qu'il ne prétend pas savoir.** Couverture
des mots du canon, puis correspondance de tête (le premier mot du premier *ou*
du deuxième segment fédéral — « Grains céréaliers, riz blanc » nomme sa classe
avant l'aliment), puis le nom de famille du canon (« Parmesan » ne dit pas qu'on
cherche un fromage; sa famille le dit), puis une pénalité par mot de trop dans le
segment de tête — beaucoup plus lourde que dans les segments suivants, parce
qu'un mot de trop devant change l'aliment (« Lait de poule » n'est pas du lait)
alors qu'un mot de trop derrière ne fait que le préciser (« Lait, liquide,
3,25 % M.G. » reste du lait).

Ce que le module ne sait pas : choisir une variété quand le canon n'en nomme
aucune. « Œuf de calibre gros » ne dit pas l'espèce, et « canard » n'est pas
plus bavard que « poule ». Sur les 25 ingrédients les plus bloquants, le premier
candidat est défendable 19 fois; les six autres échouent soit sur une variété à
choisir (œuf, lait, crème, riz), soit sur un mot que le fédéral écrit autrement
(« soya » pour du soja, aucune entrée pour la cassonade). C'est exactement le
travail qu'une session de revue règle en quelques secondes **par ingrédient**, à
condition d'avoir la liste sous les yeux : c'est la raison d'être du manifeste,
pas un défaut qu'un poids mieux réglé effacerait.


## D33 — Une masse par unité et une densité se dérivent du FCÉN, ou se refusent

**Livré.** `services/fcen_measures.py` dérive des mesures domestiques de service
(type 6) la masse d'une unité et la densité, avec la provenance à recopier, et
refuse en nommant la raison.

**Le refus qui compte : la densité de tassement.** Le FCÉN publie « 250 ml de
mozzarella râpée = 113 g ». Le rapport donne 0,45 g/ml, et ce n'est pas une
densité : c'est la façon dont des filaments occupent un contenant. Appliqué à
200 ml de lait, il rendrait 90 g au lieu de 206. Trois gardes : le libellé qui
décrit un solide découpé ou tassé est écarté (`not_pourable`), les rapports qui
sortent de la bande des liquides de cuisine aussi (0,7 à 1,5 g/ml), et deux
volumes du même aliment doivent s'accorder à 5 % près — une densité est une
constante, sinon c'est la découpe qu'on mesure.

**Le nom canonique départage l'unité.** « Ail, cru » publie « 1 gousse » (3 g)
et « 1 bulbe » (24 g), et rien dans le fichier fédéral ne dit laquelle est
l'unité de la recette. Le canon le dit : l'ingrédient s'appelle « Gousse
d'ail ». Un facteur huit se jouait sinon sur la longueur d'une étiquette.

**Appliqué : une seule masse.** `gousse_ail` = 3 g par gousse, dans
`config/cook_recipe_curation.json` (`verified_grams_per_unit` +
`grams_per_unit_provenance`), la convention qui existait déjà. Effet mesuré :
68 lignes de recette passent de bloquantes à calculées, et la raison
`missing_grams_per_unit` disparaît de l'audit. La clé n'a aucun effet sur
l'import des recettes : `import_cook_recipes.py` ne lit ces masses que pour les
ingrédients dont l'unité de base est le gramme, et `gousse_ail` se compte.

**Appliqué : six densités dérivées** — huile de canola 0,921 et cinq
condiments de 1,010 à 1,078 g/ml (vinaigres blanc, de cidre, balsamique, de vin
rouge, et moutarde de Dijon via sa substitution déclarée). Elles vivent dans
`canonical_ingredient.density_g_per_ml`, générée depuis la table `INGREDIENTS`
de `scripts/catalog_seed_data.py`, où la provenance de chacune est écrite en
commentaire à côté du chiffre — les six densités antérieures, écrites à la main,
n'en avaient aucune. L'huile d'olive garde son 0,91 : la dérivation le confirme
à 0,913, et 0,4 % d'écart ne vaut pas de déplacer les prix de 58 recettes.

Effet mesuré : `missing_density` disparaît de l'audit, **200 ingrédients
bloquants au lieu de 206**, et 508 lignes calculées au lieu de 486.

**Aucun effet sur les prix, et ce n'est pas une supposition.** Les 26 produits
appariés à ces six ingrédients sont tous vendus en volume (500 ml, 1 l, 3 l…),
donc convertis directement vers l'unité de base `ml` : aucun format en grammes,
donc aucune conversion masse↔volume, donc aucune densité lue par le calcul de
prix. Vérifié en base.

**Rectification — ce qui bloquait n'existait pas.** Cette entrée affirmait
d'abord que régénérer le catalogue déplaçait trois valeurs de récupération et
qu'il fallait réconcilier ce désaccord avant d'appliquer une densité. C'était
faux, et la vérification l'a montré : `scripts/generate_catalog.py` **préserve**
les paramètres calibrés du fichier qu'il lit, et régénérer sur `HEAD` ne change
rien du tout. Les trois valeurs vues bouger étaient une modification non
commitée déjà présente dans l'arbre de travail — le seed versionné est en retard
sur la calibration de `scripts/generate_seed.py`, qui dérive σ des produits et
des offres. Prises pour une dérive du générateur, elles ont été effacées par un
`git checkout --`, puis restaurées en rejouant la calibration (`oignon_jaune`
0,074208, `gousse_ail` 1,44, `feuille_laurier` 1,71696 — recalculées, pas
recopiées).

La leçon est consignée en test plutôt qu'en prose :
`tests/test_seed_catalog_consistency.py` fait échouer un seed dont les valeurs
calibrées ne sont plus celles de leur générateur. Un chantier n'a pas à
découvrir ce genre d'écart dans le diff d'un autre.


### D29 (suite) — Une borne porte sur les quatre nombres, pas sur l'énergie seule

**Défaut trouvé en revue.** Une ligne déclarée négligeable écrivait
`kcal_error_bound` et rien d'autre : les trois macronutriments sortaient à
`0,0 g` avec `status = "complete"`, donc **présentés comme mesurés**. La borne
de famille des épices est dérivée de la muscade à 525 kcal/100 g, qui porte
41,56 g de lipides : au plafond déclaré de 2,5 g par portion, jusqu'à **1,04 g
de gras disparaissaient en silence** pendant que les 13,2 kcal, elles,
s'affichaient. 184 lignes du corpus sont dans ce cas.

C'est exactement la faute que le module dit ne pas commettre — un chiffre
présenté comme un fait alors qu'il est une omission. Corrigé : chaque entrée
déclare les **quatre** teneurs mesurées, la borne se dérive pour chacune, et la
recette publie `kcal_`, `protein_g_`, `fat_g_` et
`carbohydrate_g_error_bound_per_serving`. L'écran affiche un « ± » **sous chaque
nombre**, jamais un seul pour les quatre.

**Les bornes de famille prennent le pire de chaque nutriment séparément.** Un
seul aliment ne borne pas les quatre : pour les épices, l'énergie et les lipides
viennent des graines de pavot (aliment 201 : 525 kcal, 41,56 g), les protéines du
persil déshydraté (197 : 26,63 g) et les glucides de la cannelle moulue (178 :
80,59 g). Prendre le profil d'un seul aliment aurait donné une borne fausse sur
les trois autres nombres.

### D30 (suite) — Le règlement nomme l'édition de l'archive, et le lecteur SQL s'y tient

**Deux défauts trouvés en revue**, tous deux latents jusqu'à l'import d'une
deuxième édition — donc invisibles aujourd'hui et certains demain :

1. La lecture du pont filtrait `source == "cnf"` sans l'édition, alors que
   l'édition fait partie de la clé unique de la table. Deux archives chargées
   faisaient porter `("2401", "2401")` à `oignon_jaune`, que le module lisait
   comme une ambiguïté : 35 recettes bloquées en citant deux fois le même
   aliment.
2. La lecture des teneurs n'avait ni filtre d'édition ni ordre, et l'import ne
   supprime pas les éditions précédentes. Avec deux archives, l'énergie pouvait
   venir de l'une et les lipides de l'autre — selon l'ordre d'arrivée des
   lignes, donc d'une requête à l'autre — et la provenance publiée nommait
   l'édition de la dernière ligne lue.

Corrigé à la source : `nutrition-rules.json` déclare `source_version`, le parseur
l'exige, et la façade restreint les trois requêtes à cette édition. Ce n'est pas
un filtre défensif mais une conséquence de D29 : une borne mesurée sur une
édition ne vaut pas pour une autre, donc les teneurs qui l'accompagnent doivent
venir de la même.

### D32 (suite) — Deux défauts de plus, trouvés en revue et non en exécutant

1. **Les taux de matière grasse étaient illisibles.** Le découpage jetait les
   nombres, donc « Crème 35 % » ne pouvait pas préférer « Crème à fouetter,
   35 % M.G. » (328 kcal, 35 g de lipides) à « Crème, légère, 5 % M.G. »
   (72 kcal, 5 g) : le classement retombait sur la brièveté du libellé et
   proposait la crème légère — **4,6 fois moins d'énergie, 7 fois moins de
   gras**. Même cause pour « Lait 3,25 % », qui ressortait sur du lait écrémé.
   Les nombres comptent désormais comme des mots : un taux n'est pas un ornement
   du nom, c'est ce qui distingue deux aliments.

2. **Un test mentait sur l'archive.** Le cas du lait était écrit avec
   `food("61", "Lait, 3,25 % M.G.")`, alors que l'aliment 61 de l'archive livrée
   est « Lait, partiellement écrémé, liquide, 2 % M.G. ». Le fichier de test
   affirme recopier les noms réels : la fixture contredisait sa propre
   docstring, et masquait le défaut ci-dessus. Corrigée sur l'aliment 113, le
   vrai lait 3,25 %.

**Un cas resté ouvert, et le commentaire qui le prétendait réglé.** « Melon,
miel (honeydew), cru » (36 kcal) passe encore devant « Confiseries, miel »
(304 kcal) pour l'ingrédient « Miel » — les deux noms portent le mot, aux mêmes
places, et rien de lexical ne distingue un fruit d'un sucre. Le commentaire de
`_RAW_BONUS` affirmait le contraire; il dit maintenant ce qui est vrai. Le bon
aliment est dans les cinq candidats, le premier est faux d'un facteur 8.

### D33 (suite) — Le calibre d'un œuf est un jugement, pas une dérivation

**Défaut trouvé en revue, sur les mesures réelles.** L'aliment 125 publie sept
calibres d'œuf — « 1 oeufs large (gros) » 52,61 g, « 1 oeuf extra gros »
58,09 g, « 1 œuf jumbo » 66,06 g, « 1 oeuf moyen » 45,62 g… Départager au plus
court libellé proposait **le jumbo pour un œuf de calibre gros : 66,06 g au lieu
de 52,61, soit 26 % de trop** sur le deuxième ingrédient le plus bloquant du
corpus (32 recettes). Deux causes se cumulaient : la ligature « œ » n'était pas
réduite ici — contrairement au module d'appariement, dont le commentaire avait
justement été écrit pour ça — donc seul le libellé accentué répondait au canon;
et rien ne pénalisait un qualificatif de calibre que le canon ne nomme pas.

Corrigé dans le sens du contrat du module, qui est de proposer **ou de refuser** :
quand plusieurs mesures de compte nomment l'ingrédient sans s'accorder entre
elles à 5 % près, la dérivation refuse (`ambiguous_count_measures`) et publie
les candidats avec leurs masses. L'ail garde ses 3 g — « 1 gousse » est la seule
mesure que « Gousse d'ail » nomme.

## D34 — Le marché de démonstration quitte le seed que la base charge

**Écart.** `docs/spec.md` (§ Données de seed) exige, dans `seed/`, « 4 magasins
dont deux partageant un `shopping_center_id` » et « ~80 produits, plusieurs
formats par ingrédient, avec des rabais actifs et un historique de prix ». Ces
fichiers existent toujours et sont toujours générés à l'identique — mais ils
vivent désormais dans `seed/demo`, pas dans `seed/main`, le seul répertoire que
`app.seeding.seed` charge dans la base réelle.

**Ce qui était réellement en base, mesuré.** Quatre épiceries inventées —
`maxiprix_lebourgneuf` (« Maxi-Prix »), `superfrais_lebourgneuf`
(« SuperFrais »), `marche_central` (« Marché Central »), `epicier_du_coin`
(« L'Épicier du Coin »), toutes situées à Montréal — portaient 83 produits
inventés (marques « Maison Rivard », « Val-Mont », « Récolte d'Or »), 564
`product_mapping`, **1 128 prix** et **2 256 offres** en `staging.raw_offer`,
sur quatre semaines. En face, un seul magasin réel avait des prix : Super C 640,
2 197 produits. Aucun croisement entre les deux ensembles — vérifié requête en
main avant de retirer quoi que ce soit, pas supposé.

**Pourquoi ce n'est pas cosmétique.** Le préfiltrage et le solveur ne font
aucune différence entre un prix capturé et un prix fabriqué : les deux sont des
lignes de `market.price`. Un plan daté dans la fenêtre synthétique (20 juillet
au 16 août 2026) pouvait donc composer un panier entier chez une bannière qui
n'existe pas, à des prix que personne ne facture, et l'écran d'épicerie
l'affichait comme une course à faire. D24 avait déjà nommé la moitié du
problème — le solveur planifiait sur 83 produits pendant que les devis en
publiaient 2 165 — et l'avait corrigé en faisant entrer le vrai catalogue.
Le faux, lui, était resté.

**Raison de le déplacer plutôt que de le supprimer.** Ces produits et ces prix
ne sont pas décoratifs : `generate_seed.py::ingredients_json` en **dérive** la
périssabilité et σ des 23 ingrédients historiques (D8), et
`tests/test_seed_catalog_consistency.py` verrouille cette dérivation. Trois
tests du solveur y lisent aussi le seul marché non trivial dont ils disposent
(prix contrastés par bannière, deux magasins en centre commercial, rabais et
historique) — `test_min_grocery_spend.py` mesure son plancher de dépense
dessus. Les supprimer aurait donc coûté la calibration de σ et la couverture
réelle du plancher de dépense, pour régler un problème qui n'est pas leur
existence mais leur **destination**.

**Mécanique.**
- `seed/main` : `stores.json` ne garde que `maxi_7552` et `superc_640` ;
  `products.json` et `raw_offers.json` n'y existent plus. Les produits et les
  prix d'un magasin réel viennent du pipeline de captures
  (`run_weekly_catalogues.py`, `import_captured_catalogue.py`), et de lui seul.
- `seed/demo` : les trois fichiers synthétiques, régénérés octet pour octet par
  `generate_seed.py` (vérifié — la calibration de σ ne bouge pas d'un chiffre).
- `app/seeding/seed.py` lit `products.json` en **optionnel**, et
  `JsonCircularAdapter` traite un `raw_offers.json` absent comme « aucune
  offre » plutôt que comme une erreur : semer un répertoire sans circulaire
  JSON n'a rien à faire atterrir, ce n'est pas une panne.
- `tests/seed_loader.py::problem_from_seed_dir` gagne `market_dir` : un test
  lit le catalogue de `seed/main` et superpose le marché de `seed/demo`. La
  séparation est explicite à l'appel, jamais implicite dans un répertoire.
- `scripts/purge_demo_market.py` retire les lignes déjà chargées (rien sans
  `--apply`), en lisant les identités de `seed/demo` et en **refusant** d'écrire
  si les deux marchés se croisent.

**Mesuré après purge sur la base de développement** : `market.store` 6 → 2,
`market.product` 2 280 → 2 197, `market.product_mapping` 2 761 → 2 197,
`market.price` 5 240 → 4 112, `staging.raw_offer` 6 368 → 4 112 — soit
exactement les 4 magasins, 83 produits, 564 appariements, 1 128 prix et 2 256
offres que `seed/demo` déclare, et rien d'autre. Un rejeu ne trouve plus rien et
le dit. Suite complète : **468 tests passés, 0 échec, 0 sauté.**

**Ce qui reste, et qui n'est pas de ce chantier.** Le profil de ménage habite
toujours Montréal (`home_lat` 45,5285) alors que les deux bannières réelles sont
à Québec, à ~225 km : c'est un vestige de la même famille, mais l'adresse réelle
du ménage n'est pas une valeur qu'un correctif peut inventer. D26 empêche déjà
l'effet le plus grave (un magasin sans prix ne peut plus être retenu parce qu'il
est proche), et le terme de déplacement reste calculé sur une distance fausse
tant que l'adresse n'est pas corrigée dans Ménage › Préférences. `maxi_7552`
reste en base sans aucun prix : c'est un magasin réel dont la capture ne produit
encore que des titres indexés, pas une bannière fantôme.

## D35 — Les recettes de démonstration quittent le seed que la base charge

**Écart.** `docs/spec.md` (§ Données de seed) exige « ~40 recettes **fictives**
mais cohérentes, partageant délibérément des ingrédients pour que la
mutualisation opère, avec des τ^fixe et β_r variés ». Ces recettes existent
toujours et sont toujours générées à l'identique — mais elles vivent désormais
dans `seed/demo`, pas dans `seed/main`, le seul répertoire que
`app.seeding.seed` charge dans la base réelle.

**Ce qui était réellement en base.** Quarante plats inventés : vingt bases
(« Chili aux lentilles », « Galettes de lentilles », « Saag au tofu », « Pâté
chinois revisité »…) et leurs vingt déclinaisons `_familial`, dérivées par
formule (π×2, τ^fixe×1,3, τ^marg×0,8, quantités fixes×1,5). Aucune source :
ni URL, ni livre, ni `import_origin` — le plat, les portions et les quantités
ont été posés à la main pour que le solveur ait de quoi arbitrer.
`services/recipe_quality.py` les reconnaissait déjà comme telles et les
exemptait de la règle « un rendement se lit dans la source » : « ses portions
sont un choix, pas la lecture d'une source ».

**Pourquoi ce n'est pas cosmétique.** Le solveur ne fait aucune différence
entre une recette importée et une recette fabriquée : les deux sont des lignes
de `catalog.recipe`. Et elles ne restaient pas dans un coin — D24 mesurait déjà
un menu composé de « chili aux lentilles, galettes de lentilles, riz frit et
sauté de tofu, à 1,00 $/portion », et D25 constatait que sous le drapeau par
défaut « ce filtre ramène le problème aux 40 recettes de démonstration ». Le
produit proposait donc à un vrai ménage de cuisiner des plats qui n'existent
nulle part, avec des quantités que personne n'a testées. C'est le pendant exact
de D34 côté catalogue : là, un panier chez une bannière qui n'existe pas ; ici,
un menu de plats qui n'existent pas.

**Raison de les déplacer plutôt que de les supprimer.** Elles sont les seules
que le marché synthétique de `seed/demo` sache servir — mesuré : ses 23
ingrédients couvrent **40 des 40** recettes de démonstration et **1 des 121**
recettes importées. Les supprimer aurait coûté aux tests du solveur le seul
marché non trivial dont ils disposent (`test_min_grocery_spend.py` y mesure son
plancher de dépense), pour régler un problème qui n'est pas leur existence mais
leur **destination**.

**Mécanique.**
- `seed/main/recipes.json` : 161 → **121 recettes**, toutes importées de
  sources réelles (Ricardo, Bon pour toi, La cuisine de Jean-Philippe).
  `generate_seed.py::recipes_json` ne recopie plus que `imported_recipes.json`,
  et garde la garde anti-collision d'identifiants.
- `seed/demo/recipes.json` : les 40 recettes écrites à la main, régénérées
  octet pour octet par le même générateur (`DEMO_RECIPES`, ex-`ALL_RECIPES`).
- `tests/seed_loader.py::problem_from_seed_dir` **concatène** les recettes des
  deux répertoires quand `market_dir` en porte : un test du solveur voit alors
  les 121 importées et les 40 de démonstration, comme avant.
- `scripts/purge_demo_recipes.py` retire les lignes déjà chargées (rien sans
  `--apply`), en lisant les identifiants de `seed/demo` et en **refusant**
  d'écrire tant que `--drop-committed` ne tranche pas le sort des plans
  `committed` qui les citent.

**Pourquoi le script emporte aussi les plans.** `household.plan` cite ses
recettes par identifiant dans `servings`/`cooked`, en JSONB, sans clé
étrangère — rien ne part en cascade. Et `planning.py::_plan_view` fait
`recipes[rid]` sans garde : un plan dont une recette a disparu devient une 500,
pas une ligne manquante. Retirer les recettes sans retirer ces plans
échangerait donc un faux menu contre un écran cassé.

**Mesuré sur la base de développement, après purge** : `catalog.recipe`
161 → 121, `catalog.recipe_ingredient` 1 441 → 1 223, `household.plan`
108 → 14 — soit exactement les 40 recettes que `seed/demo` déclare et les 94
plans qui les citaient (89 `proposed`, 5 `committed`, dont deux dont tous les
produits achetés avaient déjà disparu à la purge D34). Un rejeu ne trouve plus
rien et le dit ; `app.seeding.seed --seed-dir ../seed/main` rapporte
« catalog.recipe : 121 lignes ». Suite complète : **469 tests passés, 0 échec,
0 sauté** (un de plus qu'en D34 : le nouveau script est balayé par le test
paramétré de `test_weekly_runner_wiring.py`).

**Conséquence à assumer, mesurée.** Le préfiltrage écarte une recette sans
composante marginale quand `enable_batch_fixed_cost` est éteint (D25), et les
121 recettes importées sont **toutes** dans ce cas. Sur `seed/main` seul, au
20 août 2026 :

| recettes fournies | `enable_batch_fixed_cost` | survivantes |
| --- | --- | --- |
| 121 importées | `False` (défaut) | **0** |
| 121 importées | `True` | 81 |
| 161 (avec démo) | `False` | 40 |
| 161 (avec démo) | `True` | 121 |

Autrement dit, les 40 recettes inventées étaient ce qui masquait le fait que la
configuration par défaut ne sait rien faire du corpus réel. Le défaut de
`SolverConfig.enable_batch_fixed_cost` (`False`) doit passer à `True` pour que
le produit reste utilisable sur son propre catalogue — D25 le disait déjà (« le
défaut du front-end est un défaut de développement, pas un défaut de
produit ») ; ce chantier le rend bloquant au lieu de latent. **Ce basculement
n'est pas fait ici** : il change l'équation de besoin de toutes les recettes et
mérite son propre écart, mesuré.


## D36 — Un aliment FCÉN se rattache aussi par le règlement, et 205 choix sont écrits par un outil

**Constat mesuré.** Sur les 198 ingrédients qui bloquaient le calcul
nutritionnel le 21 août 2026, **189 portaient `no_cnf_food`** : la curation
d'identité (D20, D30) ne leur avait rattaché aucun aliment fédéral. Aucun des
trois titres de décision de D30 ne décrit ce cas : `primary` est refusé par
construction (l'aliment n'est pas rattaché), `correction` suppose un
rattachement qui nomme une autre classe d'aliment, `substitution` suppose que le
FCÉN ne publie pas la variété. Or il la publie — « Farine de blé, tout usage,
enrichie » existe, elle n'était simplement pas rattachée, parce que le pont a
été curé pour l'**identité commerciale** sous des contrôles qu'un aliment
parfaitement nutritif peut échouer.

**Décision — un quatrième titre, `attachment`.** Il déclare exactement cela :
la curation d'identité n'a rien rattaché, le FCÉN publie l'aliment, le règlement
le retient sans réécrire le pont. Le calcul le **refuse** si l'ingrédient porte
déjà un aliment (`chosen_food_already_attached`) : sans ce refus, `attachment`
serait devenu le titre fourre-tout qui dispense de dire pourquoi un
rattachement existant ne convient pas.

**Pourquoi pas des `attach_existing` dans le seed**, comme les tickets le
prévoyaient : `seed/main/cnf_catalog_curation.json` est **régénéré en entier**
par `scripts/refine_cnf_catalog.py` depuis l'archive, et ses 738 décisions
portent le relecteur `cnf-catalog-quality-v1`. Une décision ajoutée à la main y
serait effacée au prochain passage, et elle affirmerait au passage une identité
*commerciale* que la nutrition n'a pas jugée. Le règlement, lui, est écrit à la
main par construction et daté par `rule_version`.

**La provenance n'est plus saisie : elle est rendue.** Nouveau module pur
`services/food_choice_ledger.py` (`render_food_choices`, `merge_food_choices`) et
sa commande `scripts/declare_food_choices.py`. On lui donne (ingrédient, aliment,
titre, justification écrite); il rend l'entrée avec les **quatre teneurs
publiées** transcrites de l'archive, refuse un aliment que l'archive ne publie
pas, refuse une justification vide, refuse un `attachment` sur un ingrédient
déjà rattaché et un `primary` qui n'est pas dans les aliments portés — les deux
contrôles que `parse_nutrition_rules` ne peut pas faire, puisqu'il ne voit pas le
pont. Ce module existe parce que la session précédente a **fabriqué** quatre
provenances de densité en les rétro-calculant : une provenance saisie à la main
se lit comme vérifiable sans l'être.

**Effet mesuré, sur le corpus livré (121 recettes importées).**

| étape | recettes calculables | lignes calculées | ingrédients bloquants |
| --- | --- | --- | --- |
| avant (règlement 2026-08-20c) | 1 | 444 | 198 |
| 62 choix (les plus bloquants) | 10 | 722 | 158 |
| + masses et densités dérivées | 27 | 879 | 136 |
| 83 choix de plus | 65 | 980 | 67 |
| 43 choix de plus + mesures | 98 | 1029 | 21 |
| 5 mélanges d'épices | **105** | **1050** | **16** |

`config/nutrition-rules.json` porte 205 choix d'aliment (`attachment` 131,
`substitution` 67, `primary` 6, `correction` 1 — 12 d'entre eux préexistaient à
ce chantier), `config/cook_recipe_curation.json` douze masses par unité
vérifiées dont six ajoutées ici, et `seed/main/canonical_ingredients.json`
46 densités, dont 40 dérivées du FCÉN avec leur provenance dans
`scripts/catalog_seed_data.py`.

**Deux refus de dérivation corrigés, un conservé.**

1. **Une mesure aérée écartait l'aliment entier.** Le FCÉN publie « 250 ml
   liquide » *et* « 250 ml fouetté » pour la crème 35 %. La garde refusait
   l'ingrédient dès qu'une mesure décrivait un solide tassé, donc une mesure
   d'entassement disqualifiait trois mesures d'écoulement qui s'accordent à
   1,006 g/ml. Elle écarte maintenant les mesures tassées et dérive des autres;
   un aliment dont **toutes** les mesures sont tassées — le fromage râpé — reste
   refusé, et les mesures écartées sont nommées dans la provenance.
2. **Un rendement lu comme un état.** « 250 ml liquide (donne 2 tasses
   fouettée) » : le mot « tasses » du *rendement* faisait classer comme tassée
   la seule mesure d'écoulement publiée. Ce qui suit « donne » décrit ce que la
   mesure produit, pas ce qu'elle mesure, et se coupe avant classement. Au
   passage, « fouetté » entre dans la liste des états non versables : 100 ml de
   crème fouettée pèsent la moitié de 100 ml de crème.
3. **Conservé : le calibre reste un jugement.** L'œuf, le jaune d'œuf, les deux
   tortillas et la pâte à wonton portent plusieurs mesures de compte qui
   s'accordent avec le nom canonique sans s'accorder entre elles. La dérivation
   refuse (`ambiguous_count_measures`) et la décision est écrite à la main avec
   les calibres écartés : œuf 52,61 g (gros, parmi sept calibres), jaune 18,34 g,
   tortilla de blé 49 g (17,8–20 cm, parmi quatre diamètres), tortilla de maïs
   25 g (la mesure sans diamètre du fichier), wonton 8 g (carré de 8,9 cm).
   `pain_sous_marin` illustre pourquoi ce refus doit rester : la dérivation
   propose 35 g — « 1 tranche » de pain italien — pour un pain à sous-marin
   entier. La valeur n'a **pas** été appliquée.

**Les 16 bloquants restants sont des trous du fichier fédéral, pas de la
curation**, et le test `tests/test_nutrition_coverage_pin.py` verrouille le
plancher de 105 recettes en même temps qu'il exige que chaque trou restant porte
une raison publiée :

- aucun aliment publié : pâte brisée, pâte de cari vert thaï, gnocchis frais,
  gomme de xanthane, origan frais (le fichier ne publie que l'origan moulu, à
  quatre fois l'énergie du frais — une substitution y serait un faux) ;
- aucune mesure de volume ou de compte : cognac, confiture d'abricot, sirop
  aromatisé, poudre pour boisson, pain pita, pain à sous-marin, feuille de riz ;
- des mesures qui ne s'accordent pas, ou qui décrivent un solide en dés :
  lait de coco en conserve, feuillage de fenouil, jus de cornichon, aubergines
  grillées.

**Quatre densités écrites à la main que la dérivation contredit** sont laissées
en place, et nommées dans le test plutôt que passées sous silence : crème 35 %
(seed 0,98 / FCÉN 1,006), huile d'olive (0,91 / 0,913), lait 3,25 % (1,03 /
1,031), sauce soja (1,10 / 1,078). Elles portent déjà des prix; un écart de 0,4
à 2,6 % ne vaut pas de les déplacer dans le même chantier.

**Sept constats de revue, six corrigés dans la même session.** Trois portaient
sur des refus qui n'en étaient pas :

1. **Une règle fautive était absorbée par une déclaration d'apport
   négligeable.** `_computed_line` rendait `None` pour
   `chosen_food_not_attached`, puis le recours négligeable répondait *avant* que
   la faute soit constatée : sur un ingrédient déclaré négligeable, un
   « primary » désignant un aliment non rattaché sortait `status: complete`,
   0 kcal, `missing: ()` — la règle cassée n'était nommée nulle part, et
   l'épingle de couverture ne pouvait pas la voir. Neuf ingrédients du règlement
   livré sont dans cette position. Les deux raisons de faute passent maintenant
   **avant** le recours (`_RULE_FAULTS`).
2. **Le grand livre écrivait ce que son propre parseur refuse.** Le titre
   n'était pas confronté à `CHOICE_KINDS` : `kind: "attachement"` s'écrivait, et
   le règlement livré devenait illisible — 503 sur toutes les recettes. Le titre
   est validé, et `declare_food_choices.py` **relit** le règlement fusionné
   (`parse_nutrition_rules`) avant de l'écrire.
3. **Une faute de frappe d'identifiant passait pour une décision.**
   `attached.get(id, ())` confondait « ne porte aucun aliment » et « n'existe
   pas » : l'entrée s'écrivait, versionnée, et ne débloquait rien. `attached`
   porte désormais tout le canon, et un identifiant absent est refusé.

Trois autres : un règlement à moitié écrit (`"food_choices": null`, une entrée
qui n'est pas un objet) remontait en `TypeError` depuis la couche services, donc
en 500 au lieu de la 503 nommée — la forme des blocs est validée ; `--rule-version`
refuse maintenant une version **inchangée**, ce que son propre texte d'aide
promettait ; et l'invariant produit → ingrédient canonique de
`test_canonical_catalog.py` affirme l'existence de `seed/demo/products.json` au
lieu de se taire s'il disparaît. L'épingle de couverture, elle, se saute quand
l'archive fédérale (ignorée par git) est absente : `MENU_REQUIRE_NUTRITION_ARCHIVE=1`
transforme ce saut en échec, à poser en intégration continue.

**Un défaut trouvé dans mon propre correctif, et la leçon.** La coupe de la
clause de rendement avait été écrite avec un `\b` transformé en caractère
backspace : la coupe ne s'appliquait jamais. Le test passait quand même — la
crème était bien dérivée à 1,006 g/ml, mais depuis la mesure de 100 ml, et
l'assertion cherchait la chaîne « 250 ml liquide » qui figurait dans la *liste
des mesures écartées*. Corrigé, et le test coupe désormais la provenance en deux
pour vérifier séparément la mesure retenue et les mesures écartées : chercher
une sous-chaîne dans un texte qui contient les deux ne prouve rien.

**Vérifié en exécutant : 489 tests passés, 0 échec**, dont 12 nouveaux
(règlement, grand livre, mesures, épingle de couverture). Couverture mesurée
après correctifs : 105/121, 1 050 lignes calculées, 16 bloquants.


## D37 — Ce que le fichier fédéral publie autrement : fractions, cuillères, étiquettes arrondies

**Suite immédiate de D36.** Après les 194 décisions d'appariement, seize
ingrédients bloquaient encore. Douze le faisaient pour une raison qui n'était
pas un trou du fichier fédéral, mais une **forme** que la dérivation ne savait
pas lire. Chacune a été trouvée en relisant les mesures publiées, ingrédient par
ingrédient, jamais en relisant le code.

**Trois lectures ajoutées, chacune avec son test.**

1. **Un compte fractionnaire est un compte.** Le FCÉN publie parfois la demie :
   « 1/2 pita (16,5 cm dia) = 30 g » et rien d'autre pour le pain pita. La
   division par le compte existait déjà pour « 2 oeufs = 105 g »; elle lit
   maintenant la fraction, et le pita rend 60 g par unité.
2. **La cuillère fédérale est un volume.** « 2 cuillère à table (2) = 29,1 g »
   est la seule mesure de la poudre à boisson, dont le canon se mesure au
   millilitre. À la convention canadienne (table 15 ml, thé 5 ml), c'est
   0,970 g/ml — une densité que le fichier donnait et que personne ne lisait.
3. **Une étiquette arrondie ne vote plus.** « 15 ml = 15,203 g » pour du lait de
   coco, c'est 15,92 ml à la densité des trois autres mesures : une cuillère à
   table écrite « 15 ml ». Ce libellé faisait échouer l'accord à 5 % et refusait
   une densité que 60, 100 et 125 ml donnent à l'identique. L'accord se juge
   désormais sur les volumes d'au moins 50 ml; les petits sont **cités dans la
   provenance**, plus décisifs. Deux grands volumes qui se contredisent refusent
   toujours.

**Une déclaration d'apport négligeable là où la substitution aurait menti.** Le
FCÉN ne publie pas l'origan frais, seulement l'origan moulu séché — quatre fois
l'énergie par gramme. Déclarer une substitution aurait compté du séché pour du
frais. À la place, une déclaration bornée au sens de D29 : la borne prend la
teneur du **séché** (265 kcal/100 g), qui majore le frais à masse égale, au
plafond de 4 g par portion (le double du maximum observé, 1,875 g). L'écran
affiche « 0 kcal ± 5 ».

**Trois quantités d'import fausses, révélées par le déblocage.** Elles étaient
masquées : un ingrédient bloquant ne publie pas de total. Une fois débloquées,
trois recettes sortaient un chiffre faux d'un facteur 3 à 20 — exactement ce que
ce module existe pour ne pas faire.

| recette | ingrédient | avant | après | ce que dit le fichier fédéral |
| --- | --- | --- | --- | --- |
| Sandwich fondant au thon | `pain_levain` | 2 200 g | 384 g | aliment 4063, 1 grosse tranche (15 cm) = 96 g |
| Soupe won-ton | `pate_wonton` | 454 unités | 57 unités | paquet de 454 g à 8 g l'enveloppe (aliment 4001) |
| Salade façon panzanella | `roquette` | 2 000 g | 169 g | aliment 2352, 250 ml = 21,133 g |

La cause commune : l'estimation par pièce du fichier de curation vaut pour une
**miche** et non pour une tranche; « 1 paquet (454 g) » est arrivé comme un
compte; et 8 tasses de feuilles ont été converties à 1 g/ml, soit de l'eau.

**Le défaut de mécanisme derrière ces trois-là.** Les `quantity_overrides` —
des décisions humaines écrites — n'étaient consultés que si la projection amont
était incomplète, ou si un compte avait visiblement été recopié dans un champ
mesuré, un contrôle qui ne se déclenche pas quand le canonique se compte à
l'unité. L'override du won-ton ne servait donc à rien. Un override gagne
maintenant toujours, et un test le dit.

**Effet mesuré.** 105 → **113 recettes calculables sur 121**, 1 050 → 1 058
lignes calculées, 16 → **8 ingrédients bloquants**. Les huit restants sont des
trous réels : aucun aliment publié (pâte brisée, pâte de cari vert thaï,
gnocchis frais), aucune mesure de compte (feuille de riz, pain à sous-marin —
le fichier ne publie que des tranches de pain italien), ou une seule mesure de
volume qui décrit un solide en dés (feuillage de fenouil, aubergine grillée, jus
de cornichon). Ces trois derniers demandent une décision qui n'existe pas
encore : une **masse par volume tassé**, distincte d'une densité, avec sa propre
bande de validité. Leur canon se mesure au millilitre alors que la recette
manipule un solide; c'est en amont que ça se corrige, pas par une densité de
0,37 g/ml présentée comme telle.

**Ce que la curation ne corrige pas, et qu'il faut savoir.** Dix-neuf recettes
dépassent 900 kcal par portion, et le premier suspect n'est plus une erreur de
donnée : « Bouchées d'aubergine parmigiana » compte 750 ml d'huile de friture
pour six portions (1 019 kcal par portion) parce que la recette *achète* cette
huile sans qu'on la mange. La distinction entre quantité achetée et quantité
consommée n'existe pas dans le contrat de recette — c'est un chantier, pas un
correctif.

**Cinq constats de revue, cinq corrigés.** Le plus sérieux est un piège que
cette session avait fabriqué elle-même : la dérivation de masse par unité, quand
**aucune** mesure de compte ne nommait l'ingrédient, prenait toutes les mesures
plutôt que d'échouer. Elle proposait donc 35 g — « 1 tranche » de pain italien —
pour un pain à sous-marin d'environ 85 g, sans le moindre refus, dans un rapport
qu'un curateur lit pour décider. Désormais : plusieurs mesures dont aucune ne
nomme l'ingrédient donnent `no_named_count_measure`; une mesure unique reste
prise (« 9 branches » de coriandre est la seule que l'aliment publie, et le canon
n'a pas à nommer la branche).

Les quatre autres :

1. **Le même libellé était un volume ici et un compte là.** « 2 cuillère à
   table = 29,1 g » se lisait comme 30 ml pour la densité *et* comme 14,55 g par
   unité pour la masse. Quatre lignes de l'archive 2026 sont dans ce cas. Une
   cuillère est maintenant refusée comme compte, et le motif fractionnaire de la
   cuillère est reconnu pour que « 1/2 cuillère à table » ne bascule pas dans
   l'autre lecture.
2. **Une cuillère « comble » est un tas.** Le mot rejoint la liste des états non
   versables : sinon seule la bande 0,7–1,5 g/ml séparait un écoulement d'un
   monticule.
3. **La part marginale d'une recette survit à une résolution de quantité.**
   Forcer la résolution pour tout override — nécessaire, voir plus haut — la
   remettait à zéro. Aucune recette du corpus n'était touchée; la garde manquait
   quand même.
4. **Un override dérivé n'est plus classé « estimation ».** Les trois quantités
   corrigées ici viennent d'une mesure fédérale : les voir figurer dans
   `quantity_estimates` avec une justification qui dit « masse vérifiée » était
   contradictoire. Un override peut désormais déclarer `"estimated": false`.

**Et une apostrophe.** Le canon écrit « Jaune d’œuf » (apostrophe courbe), le
fichier fédéral « 4 jaunes d'œuf » (droite) : aucun mot commun, donc un refus
qui citait la mauvaise raison. Les apostrophes sont ramenées l'une à l'autre
comme la ligature « œ » l'était déjà. Le refus du jaune reste — les deux mesures
qui le nomment se contredisent, 17 g contre 12,5 g — mais il le dit maintenant
correctement, et sa provenance cite les deux.

**Vérifié en exécutant : 499 tests passés, 0 échec.** Couverture après revue :
113/121, 1 058 lignes calculées, 8 bloquants.


### D25 (suite) — Un refus qui récite cinq causes n'en nomme aucune

**Constat, en ouvrant l'application.** Générer un plan avec la configuration de
développement répond « Aucune recette ne survit au préfiltrage : régime,
allergènes, équipement, temps de préparation ou absence de prix écartent toutes
les recettes du catalogue. » Sur le corpus réel, **aucune de ces cinq causes
n'est la bonne** : les 81 recettes qui entrent dans l'étape suivante tombent sur
le besoin identiquement nul (D25), parce qu'aucune recette importée ne porte de
composante marginale par portion et que `enable_batch_fixed_cost` est éteint par
défaut. La cause réelle n'était pas dans la liste, et le message ne disait pas
quoi faire.

**Décision.** `prefilter_recipes` publiait déjà ses compteurs par étape
(`counts_by_stage`, visibles dans le diagnostic) ; la validation les reçoit
maintenant et le refus nomme **l'étape qui a vidé le catalogue**, le nombre de
recettes qui y entraient, ce que l'étape vérifie, et — pour le besoin nul — le
drapeau à rallumer :

> Aucune recette ne survit au préfiltrage : l'étape « besoin_non_nul » a écarté
> les 81 recettes qui y entraient — aucune recette ne porte de composante
> marginale par portion, donc son besoin est identiquement nul sans les coûts
> fixes de lot (D25) : rallumer `enable_batch_fixed_cost` dans `SolverConfig`
> (onglet Paramètres) rend ces recettes modélisables.

Le paramètre est optionnel et le message générique subsiste sans compteurs : les
appelants qui ne les passent pas gardent leur comportement.

**Ce que ça ne fait pas.** Le défaut de `SolverConfig.enable_batch_fixed_cost`
reste `False`. Le basculer change l'équation de besoin de toutes les recettes et
mérite son propre écart mesuré — D35 le disait déjà, et ce constat ne fait que
rendre le symptôme lisible en attendant.


## D38 — `enable_batch_fixed_cost` est allumé par défaut

**Ce que D35 avait mesuré et laissé.** Le défaut de développement met tous les
drapeaux du `SolverConfig` à `false`, et le README explique qu'on les rallume un
à un. Mais `enable_batch_fixed_cost` n'est pas un raffinement : il change ce
qu'une recette **demande**. Éteint, une recette dont toutes les quantités sont
fixes par lot a un besoin identiquement nul et le préfiltrage l'écarte (D25).
Les 121 recettes importées sont **toutes** dans ce cas : le catalogue réel se
vide entièrement, et l'application ne sait rien planifier. D35 l'avait constaté
(« 0 recette survivante ») et laissé au chantier suivant. C'est celui-ci.

**Mesuré avant de basculer, pas après.**

| corpus | drapeau éteint | drapeau allumé |
| --- | --- | --- |
| `seed/toy` (3 recettes) | Optimal, 5 portions, objectif −3,34 $ | **identique au cent près** |
| base réelle (121 recettes importées, prix Super C) | *aucun plan* — 81 recettes écartées à l'étape « besoin non nul » | Optimal, 3 plats |

Autrement dit : là où le drapeau ne change rien, il ne change rien; là où il
change quelque chose, c'est la différence entre un plan et pas de plan.

**Décision.** `SolverConfig.enable_batch_fixed_cost = True`. Le drapeau reste
désactivable explicitement, et le README garde sa liste — il en sort seulement.

**Trois pins de tests déplacés, et pourquoi.** Aucun ne signalait un défaut :

1. `test_diagnostic_is_complete` voyait
   `alterent_les_besoins_en_ingredients: []` — la liste contient désormais
   `enable_batch_fixed_cost`, ce qui est exactement ce que ce champ doit dire.
2. `test_perishable_penalty_shifts_recipe_selection` attendait
   `omelette_toy = 3` avec la pénalité de gaspillage; c'est 2 maintenant, parce
   que la troisième portion porte un coût fixe de lot qui annule le gain. La
   bascule que le test mesure — 1 → 2 — tient toujours.
3. `test_min_grocery_spend` éteint désormais le drapeau **explicitement** : ce
   fichier mesure le plancher de dépense, un mécanisme à la fois, et le laisser
   entrer déplaçait ses chiffres sans rien dire du plancher (l'écart d'appétence
   passait de 1 % à 5,5 %).

**Vérifié en exécutant : 501 tests passés, 0 échec**, et un plan généré depuis
l'API sans toucher à aucun drapeau.


## D39 — La valeur nutritive a sa place sur chaque recette, pas seulement sur le menu

**Constat d'usage.** Le bloc « Valeur nutritive par portion » n'existait que dans
le détail d'une recette **du menu de la semaine** : trois recettes sur 121, et
seulement après avoir généré un plan. La question « combien de calories dans
cette recette ? » n'avait donc pas de réponse dans l'application pour les 118
autres.

**Livré.** Un quatrième onglet, **Recettes**
(`frontend/src/screens/Recipes.tsx`) : le catalogue paginé avec sa recherche, et
une page par recette portant la valeur nutritive par portion, ses « ± », et la
liste des ingrédients. La route `GET /api/recipes` existait déjà, requise par la
spec et restée sans appelant frontend jusqu'ici — sa docstring le disait, elle le
dit maintenant autrement.

**Un seul bloc, pas deux copies.** `NutritionBlock` (et ses libellés de raisons
de blocage) sort de `Result.tsx` vers `frontend/src/components/NutritionBlock.tsx`
et les deux écrans l'importent. Deux écrans qui affichent le même fait doivent le
lire au même endroit — ce dépôt s'est déjà fait prendre deux fois par le motif
inverse.

**Ce que la liste n'affiche pas, et pourquoi.** Pas de kcal dans les lignes de la
liste. `GET /api/recipe-nutrition` exige un `recipe_id` par choix : sans recette
nommée, elle calculerait les 121 recettes en une requête non paginée
(`api/routes.py`). Les afficher en liste demanderait une route en lot — un
chantier à part, avec sa pagination et son cache. Ici : une recette ouverte, une
requête.

**Le rendement demandé est celui que la recette publie.** L'écran demande la
nutrition à `original_servings`, jamais à un nombre choisi : une recette dont
toutes les quantités sont fixes par lot refuse toute autre valeur (« ne peut
être chiffrée que pour son rendement publié »), et c'est ce refus que l'écran
Résultat affiche quand le plan, lui, a mis la recette à l'échelle.

**Vérifié en pilotant l'application** (Playwright, msedge) : onglet Recettes →
121 au catalogue, 20 par page ; recherche « sushi » → « Boules de sushi »
ouverte à 161,9 kcal · 3,1 g · 5,9 g · 24,4 g ; recherche « lasagne » → « La
meilleure lasagne à la viande maison », hors du menu de la semaine, à
1 230,4 kcal ± 3,0 · 71,2 g ± 0,3 · 74,8 g ± 0,4 · 66,9 g ± 0,6, avec ses 20
ingrédients. `tsc -b` propre, 16 tests d'API et de module catalogue passés.
