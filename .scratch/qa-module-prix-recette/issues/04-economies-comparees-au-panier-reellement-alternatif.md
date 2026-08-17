# 04 — Les économies se comparent au panier qu'on achèterait vraiment sans la promo

**What to build:** L'économie annoncée sur un devis doit répondre à la question
que l'utilisateur se pose — « combien la promo me fait-elle gagner ? » — et donc
comparer le panier payé au panier le moins cher qu'on composerait **sans** les
promotions de la semaine.

Aujourd'hui la référence est le prix régulier **du panier choisi sous promo**.
Quand la promo rend un gros format le moins cher, on le compare à son propre prix
régulier, jamais au format qu'on aurait réellement pris. Cas reproduit : besoin
de 700 g, gros format 800 g à 3,00 $ (régulier 20,00 $, en promo) contre petit
format 800 g à 4,00 $ — le devis annonce 17,00 $ d'économie, alors que
l'alternative réelle coûte 4,00 $ et l'économie vaut 1,00 $.

Second défaut de la même formule : si le prix régulier est inférieur au prix
courant (donnée fautive), l'économie sort négative et est publiée telle quelle.

**Blocked by:** 01 — Le module de coût s'importe et se teste sans base de données.

**Status:** ready-for-agent

- [ ] La référence « prix régulier » est le panier le moins cher composé à partir
      des prix réguliers de toutes les offres candidates, pas le prix régulier du
      panier promotionnel
- [ ] Une économie n'est jamais négative : une donnée incohérente produit une
      absence d'économie et une raison, pas un nombre négatif publié
- [ ] Le rapport hebdomadaire est régénéré et l'écart sur les économies médianes
      est constaté et rapporté, pas supposé
- [ ] Test discriminant reprenant le cas 700 g / gros format en promo ci-dessus
