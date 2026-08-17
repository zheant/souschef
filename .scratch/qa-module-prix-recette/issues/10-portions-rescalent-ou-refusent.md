# 10 — Demander un autre nombre de portions rescale la recette, ou refuse

**What to build:** Demander le prix d'une recette pour 8 personnes doit donner le
prix pour 8 personnes, ou dire que la recette ne sait pas se rescaler. Jamais
répondre avec confiance un nombre faux.

**121 des 161 recettes** portent toutes leurs quantités dans la composante fixe
par lot, avec une composante marginale par portion nulle — c'est le cas de
**toutes** les recettes importées du corpus. Demander 8 portions renvoie donc la
même nourriture, le même panier, le même total ; seule la division par portion
change. Un appelant de la route HTTP n'a aucun moyen de le savoir.

Deux issues possibles, à trancher dans le ticket : rescaler proportionnellement
en le déclarant estimé, ou refuser le rescalage et le dire. Ce qui n'est pas
acceptable, c'est le silence actuel.

**Blocked by:** 01 — Le module de coût s'importe et se teste sans base de données.

**Status:** ready-for-agent

- [ ] Une recette sans composante marginale ne peut pas être chiffrée en silence
      pour un nombre de portions différent de son rendement d'origine
- [ ] Le comportement retenu (rescalage déclaré estimé, ou refus explicite) est
      écrit et justifié dans le ticket avant d'être implémenté
- [ ] La route HTTP transmet ce signal jusqu'à l'appelant
- [ ] Test sur une recette importée réelle, pas seulement sur une recette
      synthétique
