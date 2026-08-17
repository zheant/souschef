# Souschef

Souschef relie les produits observés chez les épiciers à des ingrédients de
recette stables, afin d'optimiser les menus et les achats sans confondre le
catalogue commercial avec le vocabulaire culinaire.

## Language

**Produit commercial**:
Article vendu par une bannière sous une identité et un format précis; il peut
être un ingrédient, un produit composé ou un article hors périmètre.
_Avoid_: Ingrédient du magasin, aliment canonique

**Ingrédient canonique**:
Matière achetable et utilisable comme constituant d'une recette, indépendante
d'une marque, d'un format et d'une bannière.
_Avoid_: Produit, UPC, référence FCÉN

**Lien produit-ingrédient**:
Décision auditée associant un produit commercial à exactement un ingrédient
canonique compatible avec son identité et son format.
_Avoid_: Correspondance de mots, fusion automatique

**Produit exclu**:
Produit commercial qui n'est pas un ingrédient de cuisine dans le périmètre :
plat préparé, collation, sucrerie, boisson hors recette ou produit composé.
_Avoid_: Ingrédient inconnu

**Lacune canonique**:
Produit commercial admissible comme ingrédient de cuisine, mais sans
ingrédient canonique existant ni référence canadienne suffisante.
_Avoid_: Produit exclu, échec de scraping
