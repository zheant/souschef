# 06 — Mêmes entrées, même devis

**What to build:** Deux appels identiques au même jour, sur les mêmes données,
citent le même produit, le même magasin et le même total. L'ADR promet que
« l'utilisateur peut remonter d'un total vers chaque quantité, conversion,
produit, magasin et période de validité » — une preuve qui change d'un appel à
l'autre n'est pas une preuve.

Deux causes se composent. La sélection du produit qui **valorise** la
consommation prend le premier minimum rencontré, sans départage, alors que la
sélection du produit **acheté** départage explicitement par clé de produit. Et la
requête de la façade SQL n'ordonne pas ses résultats, donc l'ordre de PostgreSQL
— non garanti — décide. Cas reproduit : deux formats au même prix unitaire, le
produit cité change selon l'ordre des offres.

**Blocked by:** 02 — La route de devis fonctionne dans la pile livrée.

**Status:** ready-for-agent

- [ ] La sélection du produit de valorisation départage les égalités par un
      critère stable et documenté, comme le fait déjà la sélection d'achat
- [ ] La requête de la façade ordonne ses résultats de façon déterministe
- [ ] Un test mélange l'ordre des offres et vérifie que le devis est identique
- [ ] Le rapport hebdomadaire, régénéré deux fois de suite, est identique octet
      pour octet
