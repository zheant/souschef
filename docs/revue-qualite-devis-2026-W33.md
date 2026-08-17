# Revue de qualité — artefact « Le prix de chaque recette », 2026-W33

Revue de l'artefact `Devis Souschef W33` (129/161 recettes chiffrées, Super C
640, semaine du 13 au 19 août 2026). Chaque constat ci-dessous a été vérifié
par calcul sur le HTML publié **et** recoupé avec la source
(`data/catalogue-reports/recipe-quotes-2026-W33.json`,
`data/catalogue-registry/superc.json`, `config/ingredient-procurement-rules.json`,
`backend/app/services/recipe_costing.py`) — rien n'est déduit de la seule
lecture de l'écran.

Documents connexes : [`adr-recipe-pricing-semantics.md`](adr-recipe-pricing-semantics.md)
(sémantique acceptée le 2026-08-13), [`recipe-pricing-roadmap.md`](recipe-pricing-roadmap.md)
(couverture).

---

## Verdict

La **présentation** est de bonne qualité : traçabilité réelle, conversions
sourcées, échecs affichés plutôt que masqués. Le **calcul affiché** est
arithmétiquement juste de bout en bout. Ce qui ne tient pas, ce sont les
**données d'entrée** et **trois chiffres de la une** qui en découlent — dont
un qui est faux par construction (le cumul des rabais) et un qui est
systématiquement absurde (le décaissement).

### Ce qui tient — vérifié, pas supposé

| Contrôle | Résultat |
|---|---|
| `coût de ligne = besoin × prix unitaire` | 1 513/1 513 lignes exactes |
| `Σ lignes = coût consommé` | 129/129 devis exacts |
| `coût consommé / portions = $ / portion` | 129/129 exacts |
| Recettes sans prix listées avec l'ingrédient bloquant | 32/32 |
| Renvois `[n]` vers une source de conversion | 33 notes, toutes rattachées |
| Recettes curées : ligne à quantité douteuse, ou avertissement | 0/40 — le bloc curé est propre |

Les 40 recettes curées ne portent **aucun** des défauts de quantité décrits
plus bas (P3), et aucun avertissement. La distinction curé/importé faite par
la page est réelle et honnête.

### Ce qui ne tient pas

| # | Problème | Gravité | Portée mesurée |
|---|---|---|---|
| P1 | Gousse d'ail facturée comme une tête d'ail entière | Bloquant | 73 lignes, 68 recettes, 59,20 $ |
| P2 | Le décaissement achète des formats absurdes (sac de 50 lb pour 1 g) | Bloquant | 521 achats sur 1 151 paient >10× le consommé |
| P3 | Quantités importées à 1-3 g, chiffrées 0,00 $ et étiquetées « exact » | Bloquant | 147 lignes, 100 recettes, 60 à 0,00 $ |
| P4 | La confiance de la recette est inexplicable depuis ses lignes | Majeur | 41 recettes « estimé » dont toutes les lignes sont « exact » |
| P5 | Le cumul « Rabais de la semaine — 570,13 $ » n'a pas de sens additif | Majeur | La une |
| P6 | Appariement produit → ingrédient pollué (produits composés) | Majeur | ≥6 canoniques touchés |
| P7 | Canoniques « non précisé » : jusqu'à 3,4× d'écart pour le même ingrédient | Moyen | ~8 familles |
| P8 | Le même produit apparaît à 2-3 prix différents | Moyen | ≥6 produits au poids |
| P9 | Taxes codées à 0 pour tout le catalogue, y compris alcool et confiserie | Moyen | Tout le catalogue |
| P10 | Les comptages doublent chaque plat (variante d'échelle) | Mineur | La une + le titre de section |

---

## Correctifs appliqués — 2026-08-13

Le diagnostic ci-dessus est laissé intact : c'est la trace de l'état mesuré
avant correction. Ce qui suit dit ce qui a changé, et ce qui reste.

| # | État | Ce qui a été fait |
|---|---|---|
| P1 | **Corrigé** | Deux conversions `gousse_ail` sourcées au FCÉN 2026 (aliment 2394 : 1 gousse = 3 g, 1 bulbe = 24 g → 8 gousses). `maxi_capture.py` applique désormais une conversion déclarée même quand les dimensions coïncident — c'est ce qui bloquait toute règle « pièce vendue → gousse ». Coût de l'ail sur l'ensemble : **59,20 $ → 7,40 $**. |
| P2 | **Corrigé** | `recipe_costing.py` choisit deux offres distinctes : meilleur prix unitaire pour le coût consommé, panier le moins cher pour le décaissement. Ratio médian acheté/requis **7,3× → 3,0×** ; décaissement cumulé **6 346,76 $ → 4 333,61 $** ; coût consommé inchangé. Verrouillé par `test_checkout_buys_the_cheapest_basket_not_the_cheapest_unit_price`. |
| P3 | **Corrigé à la source** (voir ci-dessous) | Signalement : `services/recipe_quality.py` + `quality_flags`/`reliable_recipes` dans le rapport. Puis correction des quantités elles-mêmes : **157 lignes dans 86 recettes** requantifiées. **59 → 103 devis sans réserve.** |
| P4 | **Corrigé** | L'artefact affiche un second tableau « Ce qu'il faut acheter » : produit, format, unités, quantité obtenue, surplus, prix payé et **confiance de la ligne d'achat**. La confiance d'une recette est désormais explicable depuis ce qu'elle montre. |
| P5 | **Corrigé** | La tuile cumulée est remplacée par le **rabais médian par devis** (1,76 $), avec la raison affichée : les devis partagent les mêmes emballages. |
| P6 | **Corrigé** (voir « Identité du produit » ci-dessous) | Les 15 produits composés ou transformés appariés à `gousse_ail` (naans, croûtons, pain à l'ail, cornichons, saucisses, sauce BBQ, ail haché/émincé) sont rejetés — nécessaire avant P1, sans quoi la conversion en masse aurait rendu le pain naan achetable comme de l'ail. **Reste** : l'attribut « forme d'achat » sur l'ingrédient canonique, et la revue des autres cas relevés (graines de sésame → bagels, cheddar tranché sans gras, avocat surgelé, épinards surgelés). |
| P7 | **Corrigé** | 10 `supply_rules` pour les canoniques « non précisé », vers leur variante par défaut, avec provenance. `audited_conversion` quand la substitution est le même achat (beurre, sucre, poivre, cumin, riz, champignon), `estimated` quand c'est un choix éditorial (lait 3,25 %, huile végétale, basilic séché, moutarde de Dijon). |
| P8 | **Corrigé** | Un produit au poids n'affiche plus de total reconstitué : « vendu au poids » et son prix unitaire publié, rien d'inventé. |
| P9 | **Corrigé pour les cas non ambigus** | `config/quebec-tax-rates.json` + `TaxSchedule` dans l'adaptateur : taux par rayon, appliqué par produit. L'alcool passe de 15,49 $ à 17,81 $ au décaissement. **Reste hors barème, faute de règle vérifiée** : jus selon le format, produits de boulangerie selon le nombre d'unités, portions individuelles. |
| P10 | **Corrigé** | Les sections comptent les plats distincts (variante d'échelle repliée) : « 40 devis sur 40, 20 plats distincts ». La médiane curée porte sur 20 plats, pas 40 lignes. |

**Vérifications de non-régression** : 172 tests passés, 51 sautés (ceux qui
exigent PostgreSQL, indisponible dans cette session) ; couverture mesurée
avant et après avec la configuration temporairement remise dans son état
d'origine — **280 ingrédients chiffrables sur 308 dans les deux cas, 129
devis complets, aucun ingrédient perdu**. Le chiffre « 281 » de
`recipe-pricing-roadmap.md` ne correspond à aucun rapport présent sur le
disque ; la mesure retenue ici est 280, obtenue deux fois.

### P3, deuxième temps : « 1 g » voulait dire « 1 unité »

Relevé par l'utilisateur après la première passe, et plus large que ce que le
seuil de signalement voyait : ce ne sont pas seulement les lignes sous 5 g qui
étaient fausses, c'est **toute ligne dont la source comptait des articles**.
« 3 poivrons » donnait 3 g, « 12 ailes de poulet » donnait 12 g — au-dessus du
seuil, donc invisibles.

**Cause exacte.** La projection amont (`souschef_projection` du corpus
`french_recipe_corpus_200.json`) recopie le compte d'articles de la ligne
source dans `qty_fixed_per_batch_base_unit`, un champ exprimé en grammes.
`import_cook_recipes.py` ne rappelait sa propre résolution que si la valeur
projetée était absente : une valeur fausse mais présente passait telle quelle,
et les équivalences déjà curées (`verified_grams_per_unit`) n'étaient jamais
consultées pour ces lignes. **166 lignes** dans ce cas.

**Correctif.** `_count_copied_into_measured_field` : quand la ligne source se
compte (`piece`, `unit`, `clove`, `can`…), que le canonique se mesure en g/ml,
et que la valeur projetée **égale exactement** le compte brut, la résolution
reprend la main. Puis 47 équivalences ajoutées à
`config/cook_recipe_curation.json` — **30 vérifiées au FCÉN 2026** (1 poivron
moyen = 119 g, aliment 2484 ; 1 aubergine pelée = 458 g, aliment 2088 ;
1 avocat = 201 g, aliment 1511 ; etc.), **17 estimations déclarées** pour ce
que le FCÉN ne publie pas (échalote, courgette, feuille de phyllo, tranche de
prosciutto…), chacune avec sa raison dans un nouveau bloc
`grams_per_unit_provenance`. Deux lignes comptaient en réalité des tortillas :
reclassées par `canonical_overrides` vers `tortilla` et `tortilla_mais`, avec
une conversion FCÉN 4048 (1 tortilla de maïs = 25 g) pour que le format vendu
à la masse reste chiffrable.

**Mesuré après réimport** : 166 lignes à requantifier, **0 non résolue** ;
**157 lignes modifiées dans 86 recettes** ; le coût consommé réel de 63 devis
augmente de **215,92 $ au total** (Roulades de veau à la suisse : 12,89 $ →
39,34 $ ; Ailes de poulet Buffalo : 2,23 $ → 12,69 $) ; **129 devis complets**
et **281/309 ingrédients chiffrables** (aucune perte : le +1 vient du canonique
`tortilla_mais` nouvellement utilisé) ; **103 devis sans réserve** contre 59.
Il reste **1 quantité invraisemblable** signalée, 68 ingrédients comptés deux
fois et 11 nombres de portions douteux — des défauts du corpus source, pas de
la conversion d'unités.

### Défauts résiduels : rendement, doublons, identité du produit

Troisième passe, sur les 79 défauts encore signalés après la requantification.
Deux d'entre eux se sont révélés plus graves que leur étiquette, et un
troisième était un faux positif de ma propre règle.

**Un ingrédient compté deux fois n'était pas un simple doublon d'affichage.**
`catalog.recipe_ingredient` porte `UniqueConstraint(recipe_id,
canonical_ingredient_id)` et `seeding/seed.py::_upsert` fait un
`on_conflict_do_update` : pour les 28 recettes concernées, **la dernière ligne
écrasait les précédentes en base**, pendant que le calcul de prix sur le JSON
les additionnait. Deux réponses pour une même recette selon le chemin
emprunté. Exemple mesuré : « Boulettes général Tao » demande 30 + 62,5 + 250 +
62,5 = **405 g** de fécule de maïs ; la base n'en gardait que **62,5 g**.
Corrigé à l'import (`_merge_duplicate_ingredients`) : les lignes d'un même
ingrédient sont additionnées une fois pour toutes, la trace des fusions reste
dans les tags (`merged_duplicate_ingredients`). 1 513 → 1 441 lignes, 0 doublon
restant.

**Le seuil « plus de 12 portions » était le mauvais critère.** Le corpus
publie un rendement, pas toujours un nombre de portions : « 20 boulettes »,
« 24 bouchées », « 625 ml (2 ½ tasses) ». Diviser par ce nombre comme s'il
s'agissait de portions donne un prix par portion faux d'un facteur 4 à 100.
Mais une tourtière annoncée « 24 portion(s) » est légitime — le seuil la
signalait à tort. La règle repose maintenant sur la **preuve** : le rendement
publié voyage avec la recette (`tags.servings_source`), et le défaut est
« rendement non exprimé en portions » plutôt qu'un nombre trop grand. Dix
`serving_overrides` ajoutés, chacun justifié dans `serving_override_basis`,
sous une convention écrite une fois (4 bouchées, boulettes, ailes ou saucisses
cocktail par portion ; 3 taquitos ; 2 scones ; 60 ml de salsa). La tourtière
garde ses 24 portions et n'est plus signalée.

**La dernière « quantité invraisemblable » était juste.** « Purée de piments
chipotle, ½ c. à thé (2,5 ml (3 g)) » — 3 g est exact. La famille
`conserves` mêle ingrédients de corps et condiments à la cuillère ; elle sort
de `BODY_FAMILIES`, parce qu'un faux positif sur une quantité exacte coûte
plus que la détection qu'il apporte.

### Identité du produit : un bagel n'est pas du sésame (P6)

`IdentityRules` (`adapters/maxi_capture.py`, config
`product-identity-rules.json`) refuse qu'un produit composé tienne lieu
d'ingrédient de base, **sauf** si le marqueur appartient à l'identité du
canonique lui-même : « Pain au levain » reste un pain, « Sauce BBQ » reste une
sauce barbecue grâce à son alias. La comparaison se fait par mots entiers,
pluriel toléré — un test que j'avais écrit a d'ailleurs attrapé que
« Bagels » au pluriel échappait à la première version de la règle. Trois
marqueurs ont été retirés après vérification parce qu'ils rejetaient de vrais
aliments : « sandwich » (« Bifteck sandwich d'intérieur de ronde » est une
coupe de bœuf), « beignet » (« Pêche beignet » est une variété), « soupe »
(« Soupe crème de champignons condensée » **est** l'ingrédient attendu).
**125 produits rejetés**, tous vérifiés à l'échantillon : tartes aux pommes
pour la pomme, céréales d'avoine pour l'avoine, craquelins au cheddar pour le
cheddar, cornichons sucrés pour le sucre. La règle s'applique même aux
appariements « approuvés » : les 6 831 approbations du manifeste viennent d'un
traitement en lot (`existing_exact_match`), jamais d'une relecture une à une —
c'est précisément là que ces produits s'étaient glissés.

Un second registre, `disqualifying_markers_by_ingredient`, traite les cas où
le marqueur n'est fautif que pour un ingrédient : un bouillon « sans gras »
reste un bouillon, un cheddar « sans gras » est une préparation écrémée —
deux fois moins chère au 100 g, donc gagnante systématique. Le cheddar passe
de « tranché sans gras » à un vrai cheddar (0,99 $/100 g).

**La même équivalence sert maintenant les deux côtés.** L'avocat était le cas
révélateur : le seul produit chiffrable était « Avocats en dés surgelés », non
parce qu'aucun avocat frais n'existe, mais parce que « Avocat Hass » et « Sac
d'avocats 5 ea » étaient bloqués faute de conversion « pièce → masse ». Or
l'équivalence FCÉN était déjà là, dans la curation des recettes. 46
`product_conversions` ont donc été générées **depuis les mêmes nombres et avec
la même provenance** que les quantités de recette, pour que les deux côtés ne
puissent pas diverger. Résultat sur la sélection : avocat surgelé → **Avocat
Hass**, mangue surgelée → **Mangue miel**, cornichons frais → **sac de mini
concombres**, et la figue devient chiffrable — **130 devis complets** au lieu
de 129.

**État après cette passe** : 130 devis complets, **130 sans réserve** (aucun
défaut résiduel), 282/309 ingrédients chiffrables, 1 seul ingrédient encore
bloqué par une dimension (`feuille_riz`), 180 tests passés.

**Reste à faire, nommé** : un attribut « forme d'achat » sur l'ingrédient
canonique — les listes de marqueurs par ingrédient sont un palliatif vérifié
cas par cas, pas un modèle. Les épinards et le brocoli restent achetés
surgelés, ce qui est un achat légitime mais non déclaré comme tel.

**Point d'attention hors correctif** : `config/` et `data/` ne sont pas
suivis par git dans ce dépôt. Les décisions de curation modifiées ici
(rejets de produits, conversions, barème de taxes) ne sont donc versionnées
nulle part — une perte de fichier les efface sans trace.

---

## P1 — Une gousse d'ail est facturée comme une tête entière

**Constat.** 73 lignes achètent « Ail — 5 ea — 0,80 $ » à **0,16 $ l'unité**,
en traitant 1 unité vendue = 1 gousse. Une tête d'ail contient 8 à 12 gousses.
Le prix de l'ail est donc surévalué d'un ordre de grandeur.

**Preuve.** `Chili aux lentilles` (recette **curée**) : 2 gousses → 0,32 $.
Total ail sur l'artefact : 59,20 $, soit 5,9 % du coût consommé des 68
recettes concernées. Le bloc curé n'est donc pas épargné.

**Cause.** `seed/main/canonical_ingredients.json` donne à `gousse_ail` la base
`unit`, et `config/ingredient-procurement-rules.json` ne contient **aucune**
conversion pour `gousse_ail` (32 conversions existent, aucune pour l'ail).
Conséquence en cascade dans `backend/app/adapters/maxi_capture.py:352-369` :
tous les produits d'ail vendus à la masse (« Ail 115 g », « Ail biologique
85 g », « Ail haché 250 g ») sont rejetés en `package_dimension_incompatible`,
et seuls survivent les formats « ea », dont l'unité n'a jamais été confrontée à
l'unité de la recette.

**Correctif.** Ajouter une conversion `gousse_ail` : `from_unit_kind: count`
→ nombre de gousses par tête (FCÉN, ou pesée), **et** une conversion
`mass → count` (≈ 3 g par gousse) pour rouvrir les formats à la masse qui sont
aujourd'hui exclus. Le mécanisme existe déjà et est utilisé pour
`laitue_iceberg`, `fenouil_bulbe`, `mais` — rien à écrire dans le code.

**Vérification.** Après correctif : le prix de la gousse doit tomber sous
0,05 $, et « Ail 115 g » doit apparaître comme candidat dans le rapport de
couverture.

---

## P2 — Le décaissement achète un sac de 50 lb pour 1 g de pomme de terre

**Constat.** Le décaissement affiché n'est pas seulement « élevé parce qu'on
part de rien » : il choisit le format le moins cher **à l'unité de mesure**,
donc le plus gros emballage du magasin, puis en achète un entier.

**Preuve.** `Velouté de courgettes` : 1 g de pomme de terre requis → 22 680 g
achetés (sac de 50 lb) = 19,99 $. Sur les 1 151 achats des devis complets, le
ratio médian acheté/requis est de **7,3×**, et **521 achats (45 %)** paient
plus de 10× ce qu'ils consomment. Formats retenus en boucle : farine 10 kg
(27 lignes), riz basmati 4,54 kg (14), pommes de terre 50 lb (16), oignons
5 lb (37), carottes 5 lb (26). Décaissement maximal affiché : 171,06 $ pour
52,28 $ consommés.

**Cause.** `recipe_costing.py:222` sélectionne **une seule** offre par
ingrédient, `min(candidates, key=_taxed_unit_price)`, et cette offre sert à la
fois au coût consommé (où « le moins cher à l'unité » est le bon critère) et à
la ligne d'achat (`_purchase_line`, ligne 348, qui arrondit ensuite au paquet
entier). Deux optimisations différentes, un seul choix.

**Correctif.** Dissocier les deux sélections : conserver
`min(_taxed_unit_price)` pour le coût consommé, et choisir pour la ligne
d'achat le candidat qui minimise `ceil(quantité / format) × prix taxé`. C'est
la définition même du décaissement — aujourd'hui, la valeur affichée n'est le
décaissement d'aucun acheteur réel. À défaut, afficher le surplus à côté du
montant (`surplus_quantity` existe déjà dans `PurchaseCostLine`), pour que le
chiffre cesse de se lire comme un prix.

**Vérification.** Le ratio médian acheté/requis doit chuter nettement sous 7,3,
et aucun achat ne doit plus dépasser ~50× (le pire cas légitime restant les
épices).

---

## P3 — 147 lignes à 1-3 g, dont 60 chiffrées 0,00 $ et marquées « exact »

**Constat.** Des ingrédients qui se comptent à l'unité arrivent avec une
quantité d'un ou deux grammes : « Aubergine 1 g », « Oignon jaune 1 g »,
« Lime 1 g », « Pomme de terre 1 g », « Citron 1 g ». Le coût calculé est
0,00 $ et la ligne porte l'étiquette **exact**.

**Preuve.** 147 lignes ≤ 3 g réparties sur 100 recettes ; 60 d'entre elles
(hors eau, qui relève d'une règle `essential` légitime) coûtent 0,00 $, dont
**59 étiquetées « exact »**. Seules 29 des 100 recettes portent déjà un
avertissement ⚠ — les 71 autres sont présentées sans réserve, et 75 sont
comptées parmi les « 129 chiffrées ». Aucune recette curée n'est touchée : le
défaut vient entièrement de l'import automatique.

**Cause.** Les quantités proviennent de `seed/main/imported_recipes.json` via
`scripts/import_cook_recipes.py` — un « 1 oignon » non converti se retrouve en
1 g. Le module de coût, lui, fait exactement ce qu'on lui demande. C'est aussi
une violation de l'esprit de l'ADR (« une donnée absente ne devient jamais un
coût nul ») : ici la donnée absente est la quantité, et elle devient bien un
coût nul étiqueté exact.

**Correctif.** Ajouter une garde à l'import et au devis : toute ligne dont la
quantité est inférieure à un plancher plausible pour son ingrédient (p. ex.
< 5 g pour un ingrédient dont la base est la masse mais qui se vend à la
pièce) devient `estimated` au minimum, déclenche l'avertissement ⚠ de la
recette, et sort du compte « chiffrées ».

**Vérification.** Le compte de la une doit se lire « 129 chiffrées, dont N à
vérifier », avec N ≥ 100.

---

## P4 — La confiance de la recette ne s'explique pas depuis ses lignes

**Constat.** 41 recettes portent l'étiquette « estimé » alors que **toutes**
leurs lignes d'ingrédient affichent « exact ». Le lecteur ne peut pas trouver
la cause, alors que l'encadré promet : « Chaque ligne porte son niveau de
confiance ».

**Preuve.** `Pâté chinois revisité` : 6 lignes, 6 fois « exact », recette
« estimé ». Les 41 cas contiennent tous au moins un produit « format non
publié » (viande au poids). 207 lignes sont dans ce cas, dont 150 étiquetées
« exact ».

**Cause.** `recipe_costing.py:286-289` agrège le pire niveau des lignes
d'ingrédient **et des lignes d'achat**. Une offre `variable_weight` sans
incrément publié dégrade la ligne d'achat en `estimated`
(`recipe_costing.py:361-364`, conforme à l'ADR § « Produits au poids »).
L'artefact n'affiche jamais les lignes d'achat : l'information existe, elle
n'est pas rendue.

**Correctif.** Afficher dans le détail un second tableau « Décaissement » avec
la ligne d'achat, son format supposé et sa confiance — ou, a minima, annoter
la ligne concernée : « format non publié — poids d'achat estimé ».

---

## P5 — « Rabais de la semaine — 570,13 $ » additionne des paniers qui n'existent pas ensemble

**Constat.** La tuile cumule le rabais des 129 devis. Or chaque devis est un
panier indépendant « en partant de rien » : le rabais du même litre d'huile
d'olive est compté dans chacune des 63 recettes qui en utilisent, et les deux
variantes d'échelle d'un même plat comptent deux fois le même rabais.

**Preuve.** Six paires de variantes affichent un décaissement **et** un rabais
strictement identiques (33,51 $/3,24 $ ; 31,55 $/6,14 $ ; 26,53 $/1,35 $ ;
37,11 $/6,74 $ ; 38,52 $/2,74 $ ; 19,56 $/6,14 $) — la même économie, comptée
deux fois. Le total 570,13 $ correspond bien à la somme du champ
`promotional_savings_cents` sur les 129 devis, donc le chiffre est
reproductible : c'est sa signification qui est vide.

**Correctif.** Retirer la tuile, ou la remplacer par une mesure définie sur un
panier unique : rabais **médian** par devis, ou rabais du menu réellement
planifié pour la semaine. Le même argument vaut pour toute future somme
d'agrégats par recette.

---

## P6 — L'appariement produit → ingrédient laisse passer des produits composés

**Constat.** Le registre associe à des ingrédients de base des produits qui
n'en sont pas, et le sélecteur retient parfois une forme incompatible avec
l'usage en recette.

**Preuve.**
- Canonique `gousse_ail`, produits appariés dans
  `data/catalogue-registry/superc.json` : « Pains naan à l'ail », « Croûtons
  style restaurant à l'ail et aux herbes », « Pain grillé à l'ail de style
  Texas », « Cornichons épicés avec ail », « Saucisses à l'érable et à l'ail »,
  « Sauce BBQ japonaise à l'ail rôti ». Ce sont exactement les « produits
  exclus » définis dans `CONTEXT.md`. Ils ne polluent pas encore les prix parce
  que la garde de dimension (P1) les rejette — une protection accidentelle, qui
  tombera dès qu'une conversion sera ajoutée.
- Sélections effectivement retenues et discutables : `Graines de sésame` →
  **« Bagels aux graines de sésame » 452 g**, `Cheddar` → « cheddar tranché
  **sans gras** » (18 lignes), `Bouillon de poulet` → « sans gras » (43),
  `Avocat` → « avocats en **dés surgelés** » (7), `Épinard` → « épinards hachés
  **surgelés** » (6), `Brocoli` → « fleurons **surgelés** ».

**Correctif.** Deux gestes distincts : (a) purger les produits composés des
canoniques d'ingrédient de base, au moment de la curation, en appliquant la
définition déjà écrite dans `CONTEXT.md` ; (b) porter une notion de **forme
d'achat** (frais / surgelé / conserve / transformé) sur l'ingrédient canonique,
pour que le sélecteur du moins cher ne puisse pas franchir la frontière de
forme sans règle explicite.

---

## P7 — Les canoniques « non précisé » créent un écart de prix jusqu'à 3,4×

**Constat.** Le même ingrédient réel est chiffré à des prix très différents
selon la formulation de la recette.

**Preuve.** `Cumin non précisé` → « Graines de cumin moulues » à **11,26 $ /
100 g**, alors que `Cumin moulu` → « Cumin moulu » à **3,32 $ / 100 g**.
Même famille : `Poivre non précisé` → mélange quatre poivres 4,57 $ contre
`Poivre noir` 2,69 $ ; `Lait non précisé` → **lait 0 %** ; `Huile non
précisée` → huile de tournesol ; `Basilic non précisé` → feuilles de basilic.

**Correctif.** Le mécanisme existe déjà et est utilisé pour le persil : une
`supply_rule` de type `derived` qui renvoie « non précisé » vers la variante
par défaut, avec sa provenance. Trois règles seulement existent aujourd'hui.

---

## P8 — Le même produit apparaît à deux ou trois prix

**Constat.** « Tomate — format non publié » apparaît à 5,48 $, 5,49 $ **et**
5,50 $ ; « Oignon espagnol » à 2,09 $ et 2,10 $ ; « Patate douce » à 3,95 $ et
4,00 $ ; « Concombre » et « Courgette » à 5,49 $ et 5,50 $.

**Cause.** Pour un produit au poids, l'artefact affiche un « total » qui est un
prix unitaire multiplié par un poids supposé, arrondi. Ce total n'est publié
par personne.

**Correctif.** Pour `sale_mode = variable_weight`, n'afficher que le prix
unitaire publié, sans total inventé — ou afficher explicitement le poids
supposé retenu. Le bruit au cent est aujourd'hui le symptôme visible d'une
hypothèse invisible.

---

## P9 — Les taxes sont codées à 0 pour tout le catalogue

**Constat.** Le pied de page dit « Les taxes ne sont pas incluses dans le coût
consommé ». C'est exact, mais pas par décision : `tax_rate` vaut `Decimal("0")`
par défaut (`maxi_capture.py:196`) et `scripts/quote_recipes.py` ne le
renseigne jamais. La machinerie `_taxed_unit_price` existe et multiplie par
`(1 + 0)`.

**Portée.** Sans conséquence pour l'épicerie de base (détaxée au Québec), mais
le catalogue contient de la bière (20,99 $), du vin (15,49 $), des bonbons et
des plats préparés, taxables : leur décaissement est sous-estimé de ~15 %.

**Correctif.** Renseigner `tax_rate` par produit (ou par catégorie) à
l'ingestion, et corriger la phrase du pied de page pour qu'elle décrive ce qui
est fait, pas ce qu'on suppose.

---

## P10 — Les comptages doublent chaque plat

**Constat.** « Recettes curées — 40 sur 40 chiffrées » et « Médiane 1,38 $ par
portion, sur 40 recettes » comptent 20 plats deux fois : 20 des 40 lignes sont
des « — format familial » du plat précédent. Le projet a déjà tranché ce point
ailleurs (invariant D16 : deux variantes d'échelle sont **un** plat).

**Correctif.** Compter par famille de plat, ou libeller « 20 plats, 40
variantes ». Même remarque pour « 129 / 161 ».

---

## Ordre de traitement proposé

1. **P1** (une entrée de configuration, effet immédiat sur 68 recettes dont des
   curées).
2. **P3** (garde à l'import : c'est ce qui rend 71 recettes trompeuses plutôt
   que simplement approximatives).
3. **P2** (vraie modification de `recipe_costing.py` — à faire avec un test qui
   fige le ratio acheté/requis).
4. **P5**, **P4**, **P10** (la une et la traçabilité : pas de calcul, que de
   l'honnêteté d'affichage).
5. **P6**, **P7** (curation ; le plus long, à faire contre les données réelles).
6. **P8**, **P9** (précision).
