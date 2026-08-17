# 11 — La vraisemblance a une borne supérieure

**What to build:** Le contrôle de vraisemblance doit attraper une quantité
absurdement **grande**, pas seulement absurdement petite. Sans quoi « sans
réserve » n'est pas une affirmation vérifiée.

Dans le rapport W33, **130 devis complets, 130 sans réserve** — alors que les deux
recettes les plus chères du rapport sont l'une et l'autre pilotées par des
quantités manifestement fausses, sans le moindre signalement :

| recette | quantité | portions |
|---|---|---|
| Salade panzanella (55,71 $/portion) | 2 000 g de roquette, 375 g de basilic frais | 2 |
| Sandwich fondant au thon (9,65 $/portion) | 2 200 g de pain au levain | 2 |

Trois trous distincts, à combler ensemble parce qu'ils décrivent la même règle :

1. **Aucune borne haute.** Cinq lignes dépassent 500 g par portion sans
   signalement ; les herbes et épices n'ont aucune règle du tout (basilic à
   187 g/portion). Un seuil unique en grammes ne peut pas trancher — la borne
   utile est une norme **par famille et par portion**.
2. **Comparaison stricte sur la borne basse.** Le seuil des 5 g est comparé avec
   `<` : une quantité valant exactement 5 échappe à la règle. C'est le cas de
   « 5 tranches de pain » recopié en grammes, exactement le bug déjà traité en
   session du 13 août, qui repasse par cette porte.
3. **L'absence de preuve de rendement vaut absolution.** Une trempette déclarée
   « 1 portion » pour environ 500 ml ne déclenche rien, parce que la règle exige
   une preuve de rendement dans les métadonnées et traite son absence comme une
   absence de problème.

**Blocked by:** 01 — Le module de coût s'importe et se teste sans base de données.

**Status:** ready-for-agent

- [ ] Une norme par famille et par portion borne les quantités par le haut ; sa
      provenance est écrite, pas devinée
- [ ] La borne basse est inclusive : une quantité égale au seuil est signalée
- [ ] Un rendement absent ou non prouvé n'est plus traité comme un rendement sain
- [ ] Le rapport régénéré signale la panzanella, le sandwich au thon et les figues
      rôties ; le nombre de devis « sans réserve » est rapporté honnêtement, à la
      baisse
- [ ] Aucun faux positif introduit sur une quantité juste — la règle est passée
      cas par cas sur les recettes qu'elle fait basculer, comme l'a exigé la revue
      précédente pour la purée de chipotle
