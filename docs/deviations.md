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
