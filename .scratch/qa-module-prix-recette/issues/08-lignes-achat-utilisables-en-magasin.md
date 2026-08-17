# 08 — Les lignes d'achat sont utilisables en magasin

**What to build:** Chaque ligne du décaissement autonome doit pouvoir être lue par
quelqu'un debout dans une allée. Trois défauts la rendent illisible ou absurde
dans le rapport de la semaine W33 :

- **220 lignes d'achat non entières**, dont **46** affichent une quantité du type
  `0.006000006000006000006000006000` — la quantité achetée n'est jamais quantifiée
  avant publication.
- **« Acheter 3 g d'ail »** : un produit au poids sans incrément déclaré permet
  d'acheter une fraction arbitraire, ce qui n'existe pas en caisse. L'ADR prévoit
  déjà ce cas (« le décaissement autonome est signalé estimated ») mais rien
  n'arrondit à une quantité manipulable.
- **Lignes à zéro unité** : un besoin nul produit quand même une ligne d'achat à
  0 unité / 0,00 $ qui remontera dans la liste d'épicerie.

**Blocked by:** 01 — Le module de coût s'importe et se teste sans base de données.

**Status:** ready-for-agent

- [ ] Les quantités achetées sont quantifiées à une précision fixée et documentée
      avant publication ; aucune décimale filante dans le rapport régénéré
- [ ] Un achat au poids sans incrément déclaré est arrondi à une quantité
      réellement manipulable en magasin, et le reste signalé estimé
- [ ] Aucune ligne d'achat à zéro unité n'est émise
- [ ] Le rapport hebdomadaire régénéré ne contient plus aucune des trois formes
      ci-dessus, vérifié par comptage et non par échantillon
