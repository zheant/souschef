# Prompt — Application de planification de menus optimisée par les rabais (v1)

> **Avant d'écrire la moindre ligne de code : lis cette spécification en entier.** Elle contient des décisions de modélisation contre-intuitives, justifiées dans des notes en retrait. Ne les « corrige » pas.
>
> Puis livre **uniquement les étapes 1 et 2** de la section « Ordre de livraison », et arrête-toi pour validation.

## Rôle et objectif

Tu construis la **v1 fonctionnelle** d'une application qui propose un menu hebdomadaire et une liste d'épicerie, en optimisant le coût réel du panier à partir des prix en circulaire de plusieurs épiceries.

Cette v1 est une **fondation**, pas un prototype jetable. Le scraping et le catalogue réel de recettes viendront plus tard : ils doivent être **stubbés derrière des interfaces stables**, jamais court-circuités. Le critère de réussite est qu'on puisse brancher un vrai scraper et 1000 vraies recettes sans toucher au solveur, à l'API, ni au front-end.

Copie cette spécification dans `docs/spec.md` au début du projet. Si tu t'en écartes sur un point, consigne l'écart et sa raison dans `docs/deviations.md` — ne modifie pas la spécification elle-même.

---

## Stack imposée

- **Back-end** : Python 3.12, FastAPI, Pydantic v2
- **Base de données** : PostgreSQL, un seul cluster, **schémas séparés** (`catalog`, `market`, `household`, `staging`), SQLAlchemy 2.x + Alembic
- **Solveur** : PuLP (avec HiGHS ou CBC). Le solveur doit être derrière une interface pour pouvoir être remplacé.
- **Front-end** : React + TypeScript, Vite, client API typé
- **Orchestration** : `docker-compose` (api, db, web), démarrage en une commande
- **Tests** : pytest, avec au moins une instance jouet dont l'optimum est connu et vérifié

Données de départ : **fichiers JSON versionnés** dans `seed/`, chargés par une commande de seeding idempotente. Aucune donnée en dur dans le code.

---

## Périmètre de la v1

**Inclus** : modèle de données complet, seeding, solveur MILP complet à termes désactivables, API, SPA React, rapport de diagnostic.

**Explicitement exclu** — ne l'implémente pas, mais laisse la place :
- Aucun scraping réel (interface + adaptateur JSON seulement)
- Aucune authentification : **un seul profil de ménage**, chargé depuis la configuration
- Aucun apprentissage automatique ni recommandation collaborative : l'appétence $u_r$ est un score calculé par règles
- Aucun déploiement, aucun CI/CD
- **Aucune affectation des portions à des repas datés** (voir « Structure de la demande » ci-dessous)
- **Aucune substitution d'ingrédients** (voir la note sur le champ `substitutable`)

---

## Architecture en couches

Respecte strictement cette séparation. Aucune couche ne saute par-dessus la suivante.

1. **Ingestion** — ports d'acquisition, exécution en lot, jamais dans le chemin d'une requête HTTP
2. **Données** — dépôts (repositories), aucune logique métier
3. **Services** — scoring d'appétence, préfiltrage, optimiseur
4. **API** — FastAPI, expose des résultats calculés
5. **Front-end** — SPA React

### Ports à définir (v1 = adaptateurs JSON)

```
CircularPort.fetch_week(store_id, week) -> list[RawOffer]
RecipeSourcePort.load_all() -> list[Recipe]
```

Les données brutes atterrissent dans le schéma `staging` avant normalisation, pour qu'un retraitement soit rejouable sans reperdre les données. Même avec un adaptateur JSON, respecte ce cheminement : c'est lui qu'on doit pouvoir garder tel quel quand le vrai scraper arrivera.

---

## Modèle de données

Le schéma doit porter **le modèle complet dès maintenant**, même si le solveur v1 n'exploite pas tout. Ne simplifie pas le schéma sous prétexte que la v1 est réduite.

### `catalog` — curé par les développeurs

**`canonical_ingredient`** — le référentiel pivot. Les recettes ne référencent **jamais** du texte libre.
- `id`, `name`, `unit_kind` (`mass` | `volume` | `count`), `base_unit` (g, ml, unité)
- `perishability` (0–1), `salvage_value_per_unit` → $\sigma_i$
- `density_g_per_ml` (nullable, pour conversions masse↔volume)

**`recipe`**
- `id`, `name`, `original_servings` → $\pi_r$
- `prep_time_fixed_h` → $\tau^{\text{fixe}}_r$, `prep_time_marginal_h` → $\tau^{\text{marg}}_r$
- `min_batch_servings` → $\beta_r$ (contrainte : $\ge 1$), `max_batch_servings` → $m_r$
- `tags` (jsonb), `required_equipment` (jsonb), `diet_flags`, `allergen_flags`

**`recipe_ingredient`** — la scission fixe/marginal est essentielle
- `recipe_id`, `canonical_ingredient_id`
- `qty_fixed_per_batch` → $\hat a^{\text{fixe}}_{ir}$ (croûte, fond de sauce, feuille de laurier : ne scale pas)
- `qty_marginal_per_serving` → $\hat a^{\text{marg}}_{ir}$
- `substitutable` (bool)

> **Le champ `substitutable` est réservé pour une version ultérieure.** Il est présent dans le schéma pour éviter une migration future, mais **aucune logique de la v1 ne doit le lire** — ni le solveur, ni le préfiltrage, ni l'API. N'invente pas de sémantique de substitution.

### `market` — alimenté par ingestion

**`store`** : `id`, `banner`, `address`, `lat`, `lng`, `shopping_center_id` (nullable — deux bannières au même centre commercial)

**`product`** : `id`, `canonical_ingredient_id`, `brand`, `package_size` → $v_p$, `package_unit`, `tax_rate` → $t_p$

**`price`** : `product_id`, `store_id`, `price` → $c_{ps}$, `valid_from`, `valid_to`, `is_promo`, `regular_price`
> Conserve l'historique. Sans lui, impossible de distinguer un vrai rabais d'un prix régulier annoncé en gros caractères.

**`staging.raw_offer`** : payload brut + `mapping_status` (`unmapped` | `auto` | `confirmed` | `rejected`)

**`product_mapping`** : correspondance texte brut → `canonical_ingredient_id`, avec `confidence` et `confirmed_by`. Cette table sera semi-manuelle en production ; prévois-la dès maintenant.

### `household` — profil unique en v1

**`household_profile`** : `id`, `home_lat`, `home_lng`, `time_value_per_hour` → $\kappa$, `meals_per_horizon` → $n_{\text{repas}}$, `max_store_visits`, `min_distinct_recipes`, `max_share_per_recipe`, `diet_flags`, `allergen_flags`, `available_equipment`, `max_prep_time_per_meal`

**`household_member`** : `id`, `name`, `appetite_coefficient` → $\rho_h$

**`pantry_stock`** : `canonical_ingredient_id`, `quantity` → $g_i$. Reporté d'une exécution à l'autre.

> **Préséance des paramètres.** `household_profile` est la source de vérité. Les champs homonymes de `SolverConfig` (`max_store_visits`, `min_distinct_recipes`, `max_share_per_recipe`) sont des **surcharges optionnelles** : si la valeur est `None`, on prend celle du profil. Implémente cette résolution dans une fonction unique, et fais figurer les valeurs effectivement retenues dans le rapport de diagnostic.

---

## Le modèle d'optimisation

### Structure de la demande — décision assumée

Les portions forment un **pool indifférencié** sur l'horizon : le modèle décide *quoi cuisiner et en quelle quantité*, pas *quel plat à quel repas*. Il n'y a donc **aucune variable d'affectation recette→repas** en v1.

> Ce choix est délibéré. Une affectation datée exigerait une variable indicée $(r, \text{repas})$, des contraintes de non-répétition sur jours consécutifs et une gestion de la durée de conservation des restes — soit un modèle d'un ordre de grandeur plus lourd, pour un gain que la v1 n'a pas besoin de démontrer. La diversité est plutôt assurée par les contraintes ci-dessous.

### Ensembles et variables

| Symbole | Domaine | Description |
|---|---|---|
| $x_r$ | $\mathbb{Z}_{\ge 0}$ | portions produites de la recette $r$ |
| $\delta_r$ | $\{0,1\}$ | la recette $r$ est cuisinée |
| $n_{ps}$ | $\mathbb{Z}_{\ge 0}$ | unités du produit $p$ achetées chez $s$ |
| $z_s$ | $\{0,1\}$ | l'épicerie $s$ est visitée |
| $y$ | $\{0,1\}$ | au moins une sortie a lieu |
| $w_i$ | $\mathbb{R}_{\ge 0}$ | surplus de l'ingrédient $i$ |

Demande totale : $D = n_{\text{repas}} \sum_{h \in H} \rho_h$

### Fonction objectif

$$\min Z = \sum_{p \in P}\sum_{s \in S} c_{ps}(1+t_p)\, n_{ps} \;+\; f^{\text{sortie}} y + \sum_{s \in S} f^{\text{marg}}_s z_s \;+\; \kappa \sum_{r \in R}\left(\tau^{\text{fixe}}_r \delta_r + \tau^{\text{marg}}_r x_r\right) \;-\; \sum_{i \in I} \sigma_i w_i \;-\; \sum_{r \in R} u_r x_r$$

Tous les termes sont en dollars ; il n'y a aucun poids de pondération à calibrer.

Le coût de déplacement est **scindé** : $f^{\text{sortie}}$ est payé une fois pour l'ensemble de la sortie, $f^{\text{marg}}_s$ par arrêt supplémentaire.

### Contraintes

Couverture des ingrédients, stock initial inclus :

$$\sum_{p \in P_i}\sum_{s \in S} v_p\, n_{ps} \;+\; g_i \;\ge\; \sum_{r \in R}\left(\hat a^{\text{fixe}}_{ir}\, \delta_r + \hat a^{\text{marg}}_{ir}\, x_r\right) \qquad \forall i \in I$$

Demande satisfaite : $\quad \sum_{r \in R} x_r = D$

Cohérence des lots : $\quad \beta_r \delta_r \le x_r \le m_r \delta_r \qquad \forall r$

**Diversité du menu** — deux contraintes complémentaires :

$$\sum_{r \in R} \delta_r \;\ge\; R_{\min} \qquad\qquad x_r \;\le\; \alpha D \quad \forall r$$

> **Sans elles, le modèle est structurellement monotone.** $\sum_r x_r = D$ traite toutes les portions comme interchangeables : produire $D$ portions d'une seule recette maximise la mutualisation des ingrédients et n'acquitte qu'un seul $\tau^{\text{fixe}}_r$. C'est donc très souvent l'optimum. $m_r$ seul est un garde-fou trop faible.
> Valeurs de départ : $R_{\min} = 4$, $\alpha = 0{,}3$. Les deux sont dans `household_profile`, surchargeables par `SolverConfig`.

Lien produit–magasin : $\quad n_{ps} \le M_{ps}\, z_s \qquad \forall p, s$

Lien sortie : $\quad y \ge z_s \qquad \forall s$

Plafond d'arrêts : $\quad \sum_{s \in S} z_s \le K$

Surplus — **inégalité $\le$, jamais $\ge$ ni $=$** :

$$w_i \;\le\; \sum_{p \in P_i}\sum_{s \in S} v_p\, n_{ps} \;+\; g_i \;-\; \sum_{r \in R}\left(\hat a^{\text{fixe}}_{ir}\delta_r + \hat a^{\text{marg}}_{ir} x_r\right) \qquad \forall i$$

> Avec un $\ge$, le solveur gonfle $w_i$ librement et l'objectif part à $-\infty$. Le $\le$ suffit : l'optimum le sature naturellement.

### Big-M — borne agrégée, pas individuelle

$$M_{ps} = \left\lceil \frac{D \cdot \max_{i \,:\, p \in P_i} \max_{r} \left(\hat a^{\text{marg}}_{ir} + \hat a^{\text{fixe}}_{ir}\right)}{v_p} \right\rceil$$

> Une borne fondée sur le $\max$ d'une **seule** recette est invalide : la demande réelle est agrégée sur toutes les recettes cuisinées, et une borne trop serrée rend infaisables des paniers légitimes **sans que le solveur ne le signale**.

### Paramètres calculés — formules imposées

Ces trois calculs ne doivent pas être improvisés. Chacun vit dans **une fonction unique, documentée et testée**.

**Coût de déplacement.** $f^{\text{marg}}_s$ dépend du domicile du ménage : c'est un paramètre **par utilisateur**, calculé à la construction du modèle, jamais stocké comme constante globale.

$$f^{\text{sortie}} = 4{,}00\ \$ \qquad\qquad f^{\text{marg}}_s = 1{,}50\ \$ \;+\; 0{,}60 \cdot 2 d_s$$

où $d_s$ est la distance à vol d'oiseau domicile→magasin en km, majorée de 30 % pour approximer le trajet routier. Si un magasin partage un `shopping_center_id` avec un magasin déjà visité, son terme forfaitaire de 1,50 $ tombe à 0,25 $ et la distance n'est pas recomptée.

**Appétence.** $u_r$ doit rester dans $[0, 3]$ $/portion — c'est l'échelle qui garde le terme comparable au coût d'un repas sans l'écraser. Une valeur hors de cet intervalle est une erreur de calibration, à détecter par assertion.

**Conversions d'unités.** Toute conversion masse↔volume exige `density_g_per_ml` non nul. **Lève une exception explicite si la densité est absente** — n'utilise jamais 1,0 comme valeur par défaut.

### Configuration du solveur

Expose un objet `SolverConfig` permettant de désactiver chaque mécanisme indépendamment :

```python
enable_multi_store: bool      # sinon: un seul magasin imposé, z_s et f_s retirés
enable_batch_fixed_cost: bool # sinon: delta_r et tau_fixe retirés
enable_salvage: bool          # sinon: w_i et sigma_i retirés
enable_time_cost: bool        # sinon: kappa = 0
enable_pantry_stock: bool     # sinon: g_i = 0
enable_diversity: bool        # sinon: R_min et alpha retirés
appetence_mode: "objective" | "constraint"  # -sum(u_r x_r) OU sum(u_r x_r) >= U_min
max_store_visits: int | None        # surcharge du profil
min_distinct_recipes: int | None    # surcharge du profil
max_share_per_recipe: float | None  # surcharge du profil
solver_time_limit_s: int
mip_gap: float
```

Construis chaque famille de contraintes dans une **fonction dédiée**, pas dans un bloc monolithique. Chaque drapeau doit produire un modèle valide et résoluble seul.

Défaut de développement : tout à `false`, un seul magasin, `appetence_mode="objective"`. On rallume un mécanisme à la fois.

> Note : avec `enable_diversity=false`, il est **attendu** que le solveur produise un menu monotone. Ce n'est pas un bug ; c'est la démonstration que la contrainte de diversité est nécessaire. Un test doit vérifier ce comportement dans les deux configurations.

### Assertions de validité — avant tout appel au solveur

Lève une exception explicite, jamais un avertissement silencieux :

1. **Bornitude de la récupération**, avec marge de sécurité :
$$\sigma_i \;\le\; 0{,}8 \cdot \min_{p \in P_i,\; s \in S} \frac{c_{ps}(1+t_p)}{v_p}$$
> À l'égalité stricte, acheter pour encaisser le crédit est de coût nul : le problème reste borné mais produit une masse d'optima équivalents avec des paniers absurdes.

2. $\beta_r \ge 1$ et $m_r \ge \beta_r$ pour toute recette
> Si $\beta_r = 0$, le solveur peut poser $\delta_r = 1$ avec $x_r = 0$ et payer $\tau^{\text{fixe}}_r$ pour rien.

3. Chaque `recipe_ingredient` pointe vers un `canonical_ingredient` existant ; unités compatibles avec `unit_kind`
4. Chaque ingrédient requis possède au moins un produit avec un prix valide, sinon infaisabilité garantie
5. $D > 0$, au moins un magasin, au moins une recette après préfiltrage
6. **Compatibilité des contraintes de diversité** : $R_{\min} \cdot \min_r \beta_r \le D$ et $R_{\min} \ge \lceil 1/\alpha \rceil$
> Sinon le problème est infaisable pour une raison purement arithmétique, que le message du solveur ne révélera pas.

### Réduction du problème

Avant de construire le modèle :
1. **Filtres durs** : allergènes, régime, équipement manquant, temps de préparation excessif
2. **Troncature** : conserver les 150 meilleures recettes par $u_r$

> Avec $|R| \approx 1000$, cette étape vaut plus qu'un meilleur solveur. La 400e recette d'une liste triée n'entre jamais dans un optimum.

3. **Bris de symétrie** : à prix égal pour un même produit, imposer un ordre lexicographique sur les magasins.

### Rapport de diagnostic — obligatoire

Chaque résolution retourne, en plus de la solution :

- statut du solveur, temps de résolution, gap MIP atteint
- **valeur de chaque terme de l'objectif séparément** (achats, déplacements, temps, récupération, appétence)
- **valeurs effectives des paramètres surchargeables**, avec leur provenance (profil ou `SolverConfig`)
- contraintes saturées, en particulier les couvertures d'ingrédients, le plafond d'arrêts et les contraintes de diversité
- nombre de recettes après chaque étape de préfiltrage
- surplus $w_i$ par ingrédient, avec sa valorisation
- nombre de recettes distinctes retenues et part maximale d'une recette dans $D$
- en cas d'infaisabilité : IIS si disponible, sinon la liste des assertions passées et le dernier drapeau activé

> Sans ce rapport, aucune prise sur les résultats : impossible de distinguer un bug de modélisation d'un big-M mal serré ou de données placeholder incohérentes.

---

## Scoring d'appétence — par règles, pas par apprentissage

$u_r$ en dollars-équivalents par portion, dans $[0, 3]$, calculé à partir de : correspondance des tags aux préférences déclarées, pénalité de répétition récente, bonus de saisonnalité.

Isole ce calcul derrière une interface `AppetenceScorer` : un modèle appris le remplacera plus tard.

**Point d'attention** : $u_r$ constant par portion signifie que la 8e portion de chili vaut autant que la première. Implémente une **utilité concave linéarisée par morceaux** (2 à 3 segments décroissants) — cela reste dans le MILP et modélise la lassitude bien mieux que le seul plafond $m_r$.

---

## API

```
GET    /api/household                 profil, membres, D calculé
PUT    /api/household
GET    /api/pantry
PUT    /api/pantry
POST   /api/plan          body: SolverConfig partielle → menu + liste + diagnostic
GET    /api/plan/{id}
POST   /api/plan/{id}/commit          décrémente le stock, reporte w_i vers pantry_stock
GET    /api/recipes                   filtres, pagination
GET    /api/stores
GET    /api/ingredients/unmapped      file d'attente de mapping
POST   /api/ingredients/map
```

La liste d'épicerie retournée est **groupée par magasin**, avec pour chaque ligne : produit, quantité, prix unitaire, prix total taxé, et les recettes qui la consomment.

Le report de $w_i$ vers `pantry_stock` au `commit` est ce qui rend le terme de récupération honnête : sans lui, la valeur résiduelle promise n'est jamais réalisée et $\sigma_i$ n'est qu'un biais qui pousse à suracheter.

---

## Front-end (SPA React + TypeScript)

**Écran 1 — Ménage** : membres et $\rho_h$, nombre de repas, $\kappa$, filtres durs, adresse, paramètres de diversité. Affiche $D$ calculé en direct.

**Écran 2 — Génération** : bouton, état de résolution, gestion explicite du cas infaisable avec le message du diagnostic.

**Écran 3 — Résultat** :
- Menu : recettes, portions, temps de préparation, coût attribué
- Liste d'épicerie groupée par magasin, avec sous-totaux et itinéraire suggéré
- **Décomposition du coût en cinq barres** (achats, déplacements, temps, récupération, appétence) — c'est la lecture la plus utile de tout le système

**Écran 4 — Garde-manger** : stock courant, édition manuelle.

**Écran 5 — Diagnostic (mode développeur)** : le rapport complet, drapeaux du `SolverConfig` modifiables depuis l'interface. Cet écran est un outil de travail, pas une fonctionnalité utilisateur — il n'a pas besoin d'être joli, mais il doit être exhaustif.

---

## Données de seed

Fichiers JSON dans `seed/`, suffisamment riches pour que l'optimisation soit non triviale :

- ~20 ingrédients canoniques couvrant les trois `unit_kind`, avec des périssabilités contrastées (coriandre $\sigma_i = 0$, riz proche de sa borne) et des densités renseignées pour tous les ingrédients liquides
- ~40 recettes fictives mais **cohérentes**, partageant délibérément des ingrédients pour que la mutualisation opère, avec des $\tau^{\text{fixe}}$ et $\beta_r$ variés
- 4 magasins, dont deux partageant un `shopping_center_id`, à des distances contrastées du domicile
- ~80 produits, plusieurs formats par ingrédient, avec des rabais actifs et un historique de prix

Ajoute une **instance jouet** séparée (3 recettes, 4 produits, 1 magasin) dont l'optimum est calculable à la main et vérifié par un test.

---

## Ordre de livraison

Livre par étapes et arrête-toi après l'étape 2 pour validation avant de continuer.

1. Structure du projet, docker-compose, migrations, modèles SQLAlchemy, seeding, `docs/spec.md`
2. **Point de contrôle** : présente le schéma et l'arborescence, attends confirmation
3. Assertions de validité, scoring d'appétence, préfiltrage
4. Solveur avec `SolverConfig`, rapport de diagnostic, tests sur l'instance jouet
5. API FastAPI
6. SPA React

---

## Exigences transverses

- Typage strict partout ; les unités apparaissent dans les noms de champs (`qty_g`, `price_cad`)
- **Aucun montant en flottant pour l'argent** : entiers en cents, ou `Decimal`
- Toute conversion d'unité passe par une fonction unique et testée
- Le seeding est idempotent et rejouable
- Un `README` expliquant comment lancer, comment activer les drapeaux du solveur un à un, et où brancher le vrai scraper
