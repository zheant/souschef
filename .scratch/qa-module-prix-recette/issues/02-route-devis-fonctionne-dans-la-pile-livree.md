# 02 — La route de devis fonctionne dans la pile livrée

**What to build:** Après `docker compose up --build`, appeler la route des devis
de recette retourne des devis. Elle retourne aujourd'hui une erreur 500 dès le
premier appel : les règles d'approvisionnement sont cherchées à un chemin calculé
relativement au fichier source, qui tombe hors de l'image, et le dossier de
configuration n'est ni versionné, ni copié par l'image, ni monté par compose.

La correction porte trois choses indissociables : localiser les règles par la
configuration de l'application plutôt que par une remontée de dossiers parents,
verser la configuration dans le dépôt, et la rendre présente dans l'image. Le
fichier étant relu à chaque requête, en profiter pour le charger une fois.

C'est aussi le premier ticket qui donne des tests à la façade SQL du module —
elle n'en a aucun aujourd'hui.

**Blocked by:** 01 — Le module de coût s'importe et se teste sans base de données.

**Status:** ready-for-agent

- [ ] La route des devis répond 200 avec des devis réels contre la pile démarrée
      par `docker compose up --build`, vérifié par une requête réelle, pas par
      lecture du code
- [ ] L'emplacement des règles d'approvisionnement vient de la configuration de
      l'application, avec un défaut fonctionnel en développement local
- [ ] Un fichier de règles absent ou illisible produit une erreur explicite et
      nommée au démarrage ou à l'appel, jamais une trace `FileNotFoundError` brute
- [ ] Le dossier de configuration est suivi par git et présent dans l'image
- [ ] Les règles sont chargées une fois, pas à chaque requête
- [ ] Tests de la façade SQL : filtre de date de validité, filtre magasin,
      fusion du niveau de confiance prix/produit, recette introuvable
