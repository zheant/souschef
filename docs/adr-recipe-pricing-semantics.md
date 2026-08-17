# ADR — Sémantique du prix d'une recette

Statut : accepté le 2026-08-13. Révisé le 2026-08-16 (base de valorisation,
portée du panier, confiances séparées, essentiels du ménage).

## Décision

Souschef expose trois notions distinctes et ne les additionne jamais sous un
libellé ambigu « prix de la recette » :

- `consumed_cost_cents` : valeur des quantités effectivement consommées;
- `autonomous_checkout_cents` : décaissement pour préparer la recette seule
  depuis un stock vide, après arrondissement des formats;
- le coût marginal d'un menu demeure calculé par le planificateur, après
  agrégation des recettes, des produits partagés et du stock disponible.

Le coût consommé est la valeur principale d'une carte recette. Le décaissement
autonome est montré à côté. Le coût attribué par le plan reste une mesure du
menu et ne remplace aucune des deux précédentes.

Un devis porte **deux** niveaux de confiance, pas un :
`consumed_confidence` et `checkout_confidence`, chacun agrégé depuis ses seules
composantes. Les niveaux restent `exact`, `audited_conversion`, `estimated` ou
`incomplete`. Un produit vendu au poids n'affecte que le décaissement; il ne
dégrade pas une valorisation exacte. Une conversion ou une estimation doit
conserver sa provenance. Une donnée absente rend le devis incomplet; elle ne
devient jamais un coût nul — **un prix de zéro est une donnée manquante, pas une
gratuité**, et n'est jamais retenu comme preuve de prix. Seule une règle
explicite `essential` peut attribuer un coût d'épicerie nul, comme l'eau du
robinet.

## Base de valorisation du coût consommé

Le coût consommé valorise les quantités **au prix du produit que le panier
achète réellement**, et non au meilleur prix unitaire du magasin.

Les deux nombres répondent à deux questions — ce qu'on utilise, ce qu'on
décaisse — mais ils décrivent le même produit. Valoriser au meilleur prix
unitaire faisait diverger leur identité : sur le rapport 2026-W33, 532 lignes
étaient valorisées sur un produit autre que celui acheté, et le total sortait
**9,9 % sous le prix de n'importe quel panier réel** — les pommes de terre
valorisées au sac de 50 lb (0,088 $/100 g) pendant que le panier achète un sac
de 3 lb (0,22 $/100 g). Un nombre présenté comme la valeur principale d'une
carte recette ne peut pas être un prix que le ménage ne paiera jamais.

Le meilleur prix unitaire reste publié, sous `best_unit_price_cents` : il dit ce
que l'ingrédient vaut au mieux dans le magasin, sans prétendre être ce qu'on
paie. Rien n'est perdu, seul le rôle change.

Un essentiel du ménage (`household.staple`) fait exception : il est consommé
donc valorisé, mais pas racheté, et n'a donc pas de produit acheté à suivre —
il garde le meilleur prix unitaire. Il reste bloquant si aucun produit ne le
vend : le mécanisme le rend non racheté, jamais invisible.

## Portée du panier

Le décaissement autonome décrit **une course, pas une tournée**. Le panier est
composé dans une seule bannière : la moins chère parmi celles qui couvrent tous
les ingrédients à acheter, départagée par clé de magasin.

Quand aucune bannière ne couvre l'ensemble, le devis compose au meilleur prix
disponible partout mais le **déclare** — `basket_scope` vaut alors
`multi_store` au lieu de `single_store`. Ce qu'il ne fait plus, c'est annoncer
en silence un total qui suppose deux déplacements sous un libellé qui promet
d'avoir préparé la recette seule.

## Économies promotionnelles

La référence « sans promotion » est le panier qu'on composerait réellement aux
prix réguliers, pas le prix régulier du panier promotionnel. Les deux n'ont rien
à voir dès que la promo change le format retenu : comparer un panier à
lui-même annonçait 17,00 $ d'économie là où l'alternative réelle en coûte 1,00 $
de plus. Une économie n'est jamais négative — un prix régulier inférieur au prix
courant est une donnée fautive, pas une économie à rebours.

## Rendement et rescalage

Une recette dont toutes les quantités vivent dans la composante fixe par lot
décrit un lot, pas une portion : 121 des 161 recettes du corpus sont dans ce cas.
Elle ne peut être chiffrée que pour son rendement publié. Demander un autre
nombre de portions lève `RecipeNotScalableError` plutôt que de renvoyer la même
nourriture, le même panier et un prix par portion faux.

## Produits au poids

Un produit au poids conserve le prix et la quantité de référence publiés. Si
le détaillant publie un incrément massique, l'achat est arrondi à cet
incrément. Sinon, le coût consommé reste calculable au prix unitaire, mais le
décaissement autonome est signalé `estimated`. Un poids moyen affiché reste
une preuve d'estimation et ne devient pas un emballage fixe.

## Produits dérivés

Les besoins dérivés d'un même achat parent sont agrégés avant arrondissement.
Par exemple, jus et zeste de citron partagent le même achat de citrons. Une
famille d'ingrédients ne constitue jamais, à elle seule, une preuve de cette
relation.

## Conséquences

Le calcul réside dans `RecipeCostingModule`. Les scrapers capturent les preuves
sans calculer de recette; l'API et l'interface rendent les résultats du module
sans reproduire ses formules. Les rapports hebdomadaires peuvent donc comparer
la couverture sans PostgreSQL et l'utilisateur peut remonter d'un total vers
chaque quantité, conversion, produit, magasin et période de validité.
