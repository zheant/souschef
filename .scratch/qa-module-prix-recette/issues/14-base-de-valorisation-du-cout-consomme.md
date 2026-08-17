# 14 — Trancher la base de valorisation du coût consommé

**What to build:** Le nombre principal d'une carte recette est aujourd'hui
valorisé à un prix que le ménage ne paiera jamais pour cette quantité. Ce ticket
tranche la question et implémente la décision — il ne la contourne pas.

Le coût consommé prend le meilleur prix unitaire du magasin, tous formats
confondus, indépendamment du produit que la ligne d'achat achète réellement.
Mesuré sur le rapport W33 :

- **532 lignes** d'ingrédient valorisées sur un produit **autre** que celui acheté ;
- revalorisées au prix du produit effectivement acheté, les 130 recettes complètes
  passent de **2 011,67 $ à 2 210,36 $, soit +9,9 %** ;
- écarts individuels jusqu'à ×2,24 (riz frit aux œufs, 2,24 $ → 5,01 $).

Exemple lisible : les pommes de terre sont valorisées sur le sac de 50 lb
(0,088 $/100 g) pendant que le panier achète un sac de 3 lb (0,22 $/100 g). La
carte recette affiche un prix de gros ; la liste d'épicerie facture un prix de
détail.

Le choix actuel est délibéré et documenté (« deux questions, deux choix
d'offre »). Ce qui ne l'est pas, c'est que le biais soit systématique, à sens
unique, et non déclaré à l'utilisateur. Trois issues défendables : garder la
valorisation au meilleur prix unitaire mais l'étiqueter, valoriser au produit
réellement acheté, ou publier les deux.

**Blocked by:** 09 — Deux nombres, deux confiances. *(Publier deux valorisations
honnêtement suppose que chaque nombre porte déjà sa propre confiance.)*

**Status:** ready-for-agent

- [ ] La décision est écrite et justifiée — dans l'ADR de sémantique des prix, pas
      seulement dans le code
- [ ] L'écart mesuré (+9,9 % sur le rapport W33) est reproduit avant modification,
      puis recalculé après
- [ ] La base retenue est nommée sur la carte recette : l'utilisateur sait à quel
      prix la quantité est valorisée
- [ ] Rapport hebdomadaire et artefact régénérés, écarts rapportés recette par
      recette pour les dix plus gros mouvements
