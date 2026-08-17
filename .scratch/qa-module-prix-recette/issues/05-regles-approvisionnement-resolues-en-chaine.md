# 05 — Les règles d'approvisionnement se résolvent en chaîne, et la couverture dit la même chose

**What to build:** Une règle d'approvisionnement doit se résoudre jusqu'au bout,
quelle que soit la longueur de la chaîne, et les deux modules qui lisent ces
mêmes règles doivent s'accorder sur l'ensemble des recettes chiffrables.

Le module de coût ne fait qu'un seul saut et exige un produit commercial au bout
de ce saut. Deux cas légitimes échouent :

- `derived → essential` — un bouillon dérivé de l'eau, l'eau étant déclarée
  essentielle, ressort `incomplete` au lieu de coûter zéro ;
- `derived → derived` — deux conversions enchaînées ressortent `incomplete`.

L'audit de couverture, lui, lit les **mêmes** règles avec une boucle de point fixe
écrite exprès pour les chaînes. Il annonce donc une couverture que le calcul de
prix ne sait pas livrer. Un seul résolveur, partagé, supprime la divergence par
construction plutôt que par vigilance.

**Blocked by:** 01 — Le module de coût s'importe et se teste sans base de données.

**Status:** ready-for-agent

- [ ] Une chaîne `derived → derived → produit` produit un devis complet, avec la
      provenance de chaque conversion conservée
- [ ] Une règle `derived` dont la source est `essential` produit un coût nul
      explicite, pas un devis incomplet
- [ ] Un cycle dans les règles est détecté et signalé, jamais bouclé à l'infini
      ni résolu au hasard
- [ ] Les deux modules partagent le même résolveur ; un test leur donne le même
      jeu de règles et vérifie qu'ils classent les mêmes recettes chiffrables
- [ ] Le rapport de couverture est régénéré ; tout écart avec le rapport
      précédent est expliqué, pas absorbé
