# 09 — Deux nombres, deux confiances

**What to build:** Le coût consommé et le décaissement autonome n'ont pas la même
fiabilité et ne doivent plus partager un seul niveau de confiance.

L'ADR est explicite : « le coût consommé reste calculable au prix unitaire, mais
le décaissement autonome est signalé `estimated` ». L'implémentation prend le pire
niveau de toutes les lignes, achats compris, et l'applique au devis entier — un
bœuf au poids fait basculer tout le devis en `estimated` alors que sa ligne de
consommation est `exact`. Le comportement est verrouillé par un test existant :
c'est la spec qui n'est pas tenue, pas un accident, donc le test change avec le
code.

Le changement traverse la forme du devis, donc ses lecteurs : la route HTTP, le
générateur d'artefact hebdomadaire et les types du front-end.

**Blocked by:** 08 — Les lignes d'achat sont utilisables en magasin. *(Les deux
remodèlent la même structure de devis ; les enchaîner évite de migrer deux fois
le générateur d'artefact et les types du front-end.)*

**Status:** ready-for-agent

- [ ] Le devis porte une confiance propre au coût consommé et une confiance propre
      au décaissement, chacune agrégée depuis ses seules composantes
- [ ] Un produit au poids sans incrément laisse le coût consommé `exact` et ne
      dégrade que le décaissement
- [ ] Le test qui verrouillait l'ancien comportement est mis à jour, avec sa
      raison écrite dans le test
- [ ] La route HTTP, l'artefact hebdomadaire et les types du front-end exposent
      les deux niveaux ; construction du front-end propre
