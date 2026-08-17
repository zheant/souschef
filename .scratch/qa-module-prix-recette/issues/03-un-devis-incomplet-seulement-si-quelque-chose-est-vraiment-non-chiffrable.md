# 03 — Un devis n'est incomplet que si quelque chose est vraiment non chiffrable

**What to build:** Deux comportements inversés par rapport à ce que l'ADR promet,
corrigés ensemble parce qu'ils décrivent la même frontière — quand un devis a le
droit de valoir zéro, et quand il a le droit d'être incomplet.

1. **Un prix nul ne devient jamais un coût nul.** Le filtre des offres candidates
   accepte un prix de zéro ; une telle offre remporte systématiquement la
   sélection au meilleur prix unitaire et produit une recette gratuite marquée
   `complete` / `exact`. L'ADR l'interdit explicitement : « Une donnée absente
   rend le devis incomplet ; elle ne devient jamais un coût nul. » Le garde-fou
   existe côté adaptateur de capture, pas dans le module qui déclare
   l'invariant — toute source de prix future rouvre le trou.
2. **Un besoin déjà couvert ne rend pas le devis incomplet.** Un ingrédient
   entièrement couvert par le stock déclaré, sans produit au marché, fait passer
   la recette entière en `incomplete` et annule son coût consommé, alors que la
   quantité restant à chiffrer est nulle.

Au passage : le paramètre de stock existe sur le module pur mais n'est transmis
par aucun appelant. Soit il devient atteignable, soit il est retiré — pas laissé
en promesse morte.

**Blocked by:** 01 — Le module de coût s'importe et se teste sans base de données.

**Status:** ready-for-agent

- [ ] Une offre à prix nul ou négatif n'est jamais retenue comme preuve de prix ;
      l'ingrédient concerné ressort incomplet avec une raison nommée
- [ ] Un ingrédient dont le besoin résiduel est nul n'empêche jamais un devis
      d'être complet, et ne produit aucune ligne d'achat
- [ ] Le sort du paramètre de stock est tranché : rendu atteignable depuis la
      façade, ou retiré du module
- [ ] Un test par comportement, chacun échouant sur le code actuel
