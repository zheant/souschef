# 12 — Deux faits faux retirés du catalogue

**What to build:** Deux produits publiés dans le rapport W33 sont faux, pas
approximatifs. Les corriger, et poser la règle qui empêche leur famille de
revenir.

1. **De la bière vendue comme du miel, dans 8 recettes.** Une bière forte rousse
   au miel (473 ml, taxée à 14,975 %) est approuvée sous l'ingrédient canonique
   `miel` et déclarée comme 473 g de miel — la conversion millilitres → grammes du
   miel n'est pas appliquée. Elle perd la valorisation au prix unitaire mais gagne
   la composition du panier, donc elle n'apparaît **que** côté liste d'épicerie :
   c'est pour cette raison qu'elle a survécu à la revue précédente, qui lisait
   surtout les coûts consommés. Une boisson alcoolisée est dans la liste
   d'épicerie sous le nom d'un ingrédient de base.
2. **Une demi-caisse de figues comptée comme une figue.** Le produit « demi caisse
   de figues fraîches » à 9,99 $ porte une quantité de 50 g, avec pour provenance
   l'équivalence « 1 figue moyenne = 50 g » : une équivalence pièce → masse a été
   appliquée au titre d'un format de gros. Résultat : figues à 200 $/kg, 69,93 $
   sur un décaissement de 91,26 $, et la 2ᵉ recette la plus chère du rapport.

La règle d'identité de produit existe déjà et a déjà servi à écarter 125 produits
composés. Elle ne couvre ni les formats de gros, ni les boissons alcoolisées
portant le nom d'un ingrédient. Comme lors du chantier précédent, tout marqueur
ajouté est vérifié un par un contre les produits qu'il ferait basculer — trois
marqueurs avaient alors dû être retirés parce qu'ils rejetaient de vrais aliments.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] La bière n'est plus appariée à `miel` dans aucune recette
- [ ] La demi-caisse de figues porte un format vrai, ou est écartée
- [ ] Un format de gros ne peut plus hériter d'une équivalence à la pièce
- [ ] Un produit alcoolisé ne peut plus satisfaire un ingrédient alimentaire de
      base ; les ingrédients qui sont eux-mêmes du vin ou de la bière de cuisson
      restent chiffrables
- [ ] Chaque marqueur ajouté est vérifié contre les produits qu'il fait basculer,
      et les faux rejets sont retirés avant de conclure
- [ ] Rapport régénéré : perte de couverture nulle, ou nommée ingrédient par
      ingrédient
