# Curater les candidats FCÉN

Ce flux transforme une décision humaine en changement auditable du catalogue.
Il ne tourne jamais dans une requête HTTP et aucune famille d'ingrédients
n'est lue par le solveur, le préfiltrage ou le calcul des besoins.

## 1. Prévisualiser un candidat

Depuis `backend/` :

```bash
python -m app.ingestion.ingredient_curation preview \
  --source-version 2026 --food-code 1234
```

La réponse montre les correspondances exactes et les libellés très proches
parmi les noms canoniques et alias déjà approuvés. Ce sont des avertissements,
jamais des décisions automatiques.

## 2. Écrire un manifeste versionné

Le document accepte une liste `decisions`. Les trois actions possibles sont :

- `attach_existing` : rattache le code FCÉN à une identité existante;
- `create_variant` : crée une identité achetable distincte dans une famille;
- `exclude` : rejette humainement un plat, snack ou état non achetable.

Exemple montrant les trois formes :

```json
{
  "decisions": [
    {
      "source_version": "2026",
      "food_code": "<CODE_FCEN_EXISTANT>",
      "action": "attach_existing",
      "canonical_ingredient_id": "riz_basmati",
      "reviewer": "prenom.nom",
      "rationale": "Même identité achetable; la différence FCÉN est nutritionnelle.",
      "aliases": [
        {"language": "fr", "alias": "Riz basmati sec"}
      ]
    },
    {
      "source_version": "2026",
      "food_code": "<CODE_FCEN_VARIANTE>",
      "action": "create_variant",
      "reviewer": "prenom.nom",
      "rationale": "Variante explicitement vendue séparément dans le catalogue d'épicerie.",
      "canonical": {
        "id": "riz_jasmin",
        "family_id": "riz",
        "name": "Riz jasmin",
        "unit_kind": "mass",
        "base_unit": "g",
        "perishability": null,
        "salvage_value_cents_per_base_unit": null,
        "density_g_per_ml": null
      },
      "aliases": [
        {"language": "en", "alias": "Jasmine rice"}
      ],
      "acknowledged_similar_ids": ["riz_basmati"]
    },
    {
      "source_version": "2026",
      "food_code": "<CODE_FCEN_EXCLU>",
      "action": "exclude",
      "reviewer": "prenom.nom",
      "rationale": "Plat préparé, pas un ingrédient achetable de recette."
    }
  ]
}
```

Les champs métier du nouveau canon ne sont jamais déduits du FCÉN.
`perishability` et `salvage_value_cents_per_base_unit` restent à `null` tant
qu'une curation dédiée ne les justifie; une densité connue peut être fournie.
Les descriptions FCÉN ne deviennent pas automatiquement des alias; seules les
entrées explicites de `aliases` sont approuvées.

## 3. Appliquer et rejouer

```bash
python -m app.ingestion.ingredient_curation apply \
  --manifest ../data/curation-riz.json
```

Chaque décision écrit un événement append-only avec l'auteur, la justification,
le payload de décision et un instantané du candidat. Rejouer exactement le même
manifeste retourne `replayed: true` sans dupliquer le canon, l'alias, le crosswalk
ou l'événement. Une décision corrigée crée un nouvel événement d'audit.

## Famille `riz`

`catalog.ingredient_family` sert uniquement au classement et à la détection
pendant la curation. `riz_basmati` appartient à la famille `riz`; une variante
justifiée, par exemple `riz_jasmin`, reçoit sa propre identité canonique. Les
marques et formats Maxi restent des lignes `market.product` rattachées à
l'identité précise. Une famille n'est donc ni un ingrédient de recette ni une
cible de produit.
