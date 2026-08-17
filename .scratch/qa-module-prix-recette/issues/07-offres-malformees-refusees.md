# 07 — Une offre malformée est refusée, pas lissée

**What to build:** Quand une offre ne décrit pas un achat réalisable, le devis le
dit. Il ne fabrique pas un nombre vraisemblable par défaut.

Deux cas aujourd'hui silencieux :

1. **Mode de vente inconnu.** Toute valeur autre que le format fixe, et sans
   incrément d'achat déclaré, tombe dans la branche « acheter exactement le
   besoin » et se contente d'abaisser la confiance. Une faute de frappe dans une
   donnée de curation devient un décaissement plausible mais faux (reproduit :
   besoin de 150 g sur un format de 1000 g → 0,15 unité achetée).
2. **Fenêtre de validité incohérente.** La période du devis est le plus tard des
   débuts et le plus tôt des fins ; des offres aux fenêtres disjointes produisent
   une fenêtre vide, publiée sans signal (reproduit : validité du 20 août au
   19 août).

**Blocked by:** 01 — Le module de coût s'importe et se teste sans base de données.

**Status:** ready-for-agent

- [ ] Un mode de vente non reconnu lève une erreur nommée au lieu d'être traité
      comme un achat au besoin exact
- [ ] Les modes de vente acceptés sont énumérés à un seul endroit, pas déduits
      par élimination dans la logique d'achat
- [ ] Une fenêtre de validité vide n'est jamais publiée : le devis porte une
      raison explicite et ne prétend pas être valable sur une période impossible
- [ ] Un test par cas, chacun échouant sur le code actuel
