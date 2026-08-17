# 13 — Les essentiels du ménage cessent d'être rachetés de zéro

**What to build:** Le décaissement autonome d'une recette ne doit plus facturer un
sac de sel entier pour une pincée. Le ménage déclare déjà ses essentiels — le
module de prix ne les lit pas.

Une seule règle `essential` est déclarée aujourd'hui : l'eau. Tout le reste
s'achète en entier. Mesuré sur le rapport W33 :

| ingrédient | recettes achetant plus de 20× le besoin |
|---|---|
| sel de table | 27 (1,25 g requis → sac de 1 kg à 1,99 $, soit ×800) |
| huile d'olive | 19 |
| huile végétale | 13 |
| farine tout usage | 12 |
| feuille de laurier | 10 |
| jus de citron, poivre noir | 8 chacun |

Multiple de surplus médian toutes lignes confondues : 2,65×. **18 recettes** ont
un décaissement supérieur à 5× leur coût consommé. Cas extrême : une trempette
ranch d'une portion, **7,80 $ consommés contre 41,81 $ à décaisser**, dont 11
condiments de garde-manger sur 14 achats.

Le concept d'essentiels existe déjà côté solveur, avec sa table et son drapeau.
Ce ticket le rend visible du module de prix, sans dupliquer la liste à la main
dans le fichier de règles.

**Blocked by:** 05 — Les règles d'approvisionnement se résolvent en chaîne.

**Status:** ready-for-agent

- [ ] Les essentiels déclarés par le ménage sont visibles du calcul de prix sans
      recopie manuelle dans le fichier de règles
- [ ] Un essentiel ne produit pas de ligne d'achat au décaissement autonome, et
      son traitement est visible sur la ligne d'ingrédient plutôt que muet
- [ ] Un essentiel dont le ménage n'a en fait rien reste chiffrable — le mécanisme
      ne rend pas l'ingrédient invisible, seulement non racheté
- [ ] Rapport régénéré : décaissement médian et nombre de recettes au-delà de 5×
      le coût consommé rapportés avant/après
