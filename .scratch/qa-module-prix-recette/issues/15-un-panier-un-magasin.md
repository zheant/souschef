# 15 — Un panier, un magasin

**What to build:** Le décaissement autonome d'une recette doit correspondre à une
course qu'on peut réellement faire. Rien n'impose aujourd'hui un magasin unique,
et la route HTTP n'en filtre aucun par défaut.

Cas reproduit : une recette à deux ingrédients, le riz chez un détaillant et le
bœuf chez l'autre, ressort avec les deux magasins et un décaissement de 12,48 $
qui suppose deux déplacements — sans coût de déplacement, sans signal, sous un
libellé qui promet le contraire (« préparer la recette seule depuis un stock
vide »).

Le rapport W33 ne le montre pas parce qu'il n'a tourné que sur un seul magasin.
Le défaut est structurel, pas hypothétique : il apparaîtra au premier rapport
multi-bannières.

Deux issues défendables, à trancher dans le ticket : composer le panier le moins
cher **par magasin** et retenir le meilleur, ou autoriser le multi-magasin en
l'affichant comme tel. Le planificateur de menu a déjà un traitement du
multi-magasin et de son coût de déplacement — s'en inspirer plutôt que d'inventer
un second modèle.

**Blocked by:** 02 — La route de devis fonctionne dans la pile livrée.

**Status:** ready-for-agent

- [ ] La politique retenue est écrite dans l'ADR de sémantique des prix
- [ ] Un devis ne peut plus annoncer un décaissement réparti sur plusieurs
      magasins sans le dire explicitement
- [ ] Le défaut de la route HTTP correspond à la politique retenue
- [ ] Test sur des offres réparties entre deux bannières, échouant sur le code
      actuel
- [ ] Un rapport est produit sur deux bannières et son décaissement est confronté
      à la politique retenue, pas seulement calculé
