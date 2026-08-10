# Souschef — synthèse produit et périmètre du pilote

## Vision du produit

Souschef aide les familles québécoises de 2 à 5 personnes à planifier
rapidement leurs repas tout en réduisant leur facture grâce aux rabais.

> Planifiez vos repas et votre épicerie en quelques minutes, en profitant
> automatiquement des rabais.

La planification et le gain de temps sont les bénéfices immédiats;
l'optimisation économique constitue le différenciateur.

## Parcours du pilote

1. L'utilisateur répond à un questionnaire de moins de trois minutes :
   - membres du ménage et appétit exprimé simplement;
   - repas à couvrir;
   - sorties et invités prévus;
   - restrictions obligatoires;
   - temps disponible;
   - magasins accessibles;
   - programmes de fidélité publics auxquels il adhère.
2. Souschef génère un premier menu à partir de vrais prix locaux, d'un
   catalogue limité et curé et de paramètres inférés. Ces paramètres sont
   résumés en langage naturel plutôt qu'exposés sous leur forme mathématique.
3. Souschef présente une liste d'épicerie préliminaire.
4. L'utilisateur indique les produits qu'il possède déjà (`assez` ou `un
   peu`) et les périssables à utiliser en priorité ou obligatoirement.
5. Souschef réoptimise le menu et explique les changements apportés.
6. L'utilisateur peut garder ou verrouiller une recette, la remplacer,
   indiquer qu'il ne l'aime pas, accepter un compromis de coût ou de
   gaspillage, ou conserver le premier plan.
7. La liste finale est offerte par magasin et catégorie, avec une vue
   détaillée des prix, formats, rabais et économies. Elle peut être partagée
   et synchronisée entre les membres du ménage.

## Principes de conception

- L'utilisateur garde toujours le dernier mot.
- Une allergie ou une restriction obligatoire n'est jamais violée.
- Une préférence peut faire l'objet d'un compromis clairement expliqué.
- Un remplacement n'est jamais refusé pour des raisons économiques. Si son
  coût ou son gaspillage dépasse un seuil, Souschef avertit l'utilisateur et
  lui laisse la décision.
- Souschef tente d'abord un remplacement local. Une réoptimisation plus large
  est proposée si le compromis demeure mauvais.
- Une réoptimisation ne change jamais silencieusement les recettes
  verrouillées.
- Les paramètres mathématiques restent cachés derrière des choix
  compréhensibles et modifiables.
- Un rejet distingue `cette semaine`, `moins souvent` et `ne plus proposer`.
  Le rejet d'une recette n'est pas automatiquement interprété comme le rejet
  de ses ingrédients.
- Les préférences apprises sont consultables, corrigibles et effaçables.
- Les prix estimés et les prix réservés aux membres sont clairement signalés.
- Un deuxième magasin est présenté comme une option avec son économie nette.
- Les économies sont comparées à des références honnêtes et séparées : prix
  réguliers des mêmes produits et achat du même panier dans le magasin
  habituel.
- Le décaissement de la semaine est distingué de la valeur des produits déjà
  disponibles dans le garde-manger.

## Questionnaire initial et routine hebdomadaire

Le questionnaire initial doit prendre moins de trois minutes. Les préférences
non essentielles peuvent être ignorées et complétées plus tard.

Les coefficients d'appétit ne sont pas exposés. L'utilisateur choisit des
catégories simples comme petit, moyen ou grand appétit; Souschef les traduit
en paramètres internes.

Après le questionnaire, Souschef présente un résumé lisible, par exemple :
« 4 personnes, 9 repas à prévoir, cuisine rapide, une épicerie privilégiée,
variété moyenne ».

Lors des semaines suivantes, un check-in de moins d'une minute recueille
seulement les exceptions : repas à l'extérieur, invités, aliments à utiliser
et contraintes particulières. Le profil permanent reste prérempli et peut
être modifié.

## Confirmation du garde-manger

Souschef ne demande pas un inventaire exhaustif avant de fournir de la valeur.
Il génère d'abord un menu et une liste préliminaire, puis demande à
l'utilisateur ce qu'il possède déjà.

L'état non coché signifie que le produit n'est pas disponible. Pour un
produit coché, l'utilisateur indique `assez` ou `un peu`; une quantité précise
reste facultative. L'interface priorise les ingrédients coûteux, périssables
ou requis en grande quantité et présélectionne raisonnablement certains
essentiels courants.

Les aliments périssables disposent de deux niveaux :

- `utiliser en priorité`, traité comme une préférence;
- `doit être utilisé`, traité comme une contrainte.

Cette contrainte ne signifie pas automatiquement que toute la quantité doit
être consommée, puisque les quantités déclarées peuvent être approximatives.
Si aucune recette compatible n'utilise l'aliment, Souschef propose de relâcher
une préférence, d'ajouter une recette simple ou de retirer l'obligation.

## Remplacement et réoptimisation

Lorsqu'une recette est remplacée, Souschef affiche les conséquences sur le
coût et le gaspillage. Deux seuils distincts sont utilisés : hausse du panier
supérieure à 5 $ ou 10 %, et surplus périssable significatif.

Souschef tente d'abord de remplacer seulement la recette concernée. Si le
résultat reste mauvais, il propose une réoptimisation plus large sans changer
les recettes que l'utilisateur a explicitement verrouillées.

Après la confirmation du garde-manger, toute modification du premier menu est
expliquée, par exemple : « Deux recettes ont été remplacées pour utiliser vos
poivrons et économiser 4,80 $ ». L'utilisateur peut conserver la proposition
initiale.

## Repas et accompagnements

Le catalogue curé distingue :

- les plats complets;
- les plats qui nécessitent un accompagnement;
- une banque d'accompagnements compatibles.

Cette classification et les compatibilités sont définies et validées par
l'équipe Souschef. Pour un plat incomplet, le solveur sélectionne un
accompagnement parmi sa banque de compatibilités. L'ensemble compte comme un
seul repas et l'accompagnement ne gonfle pas artificiellement la diversité.

Les accompagnements sont diversifiés et leurs préférences sont apprises
séparément de celles du plat principal. Ils peuvent être remplacés localement
ou préparés en lots partagés pour plusieurs repas. L'interface indique alors
les portions à réserver.

L'ensemble équilibré est proposé par défaut, mais l'utilisateur peut retirer
l'accompagnement après un avertissement léger. Les portions sont calibrées
pour l'ensemble du repas, pas simplement additionnées.

Dans l'interface, un ensemble apparaît comme une seule carte, par exemple
« Lasagne + salade verte », qui ouvre ensuite les blocs de préparation du
plat et de l'accompagnement.

## Temps de préparation et cuisine guidée

Les recettes distinguent le temps de travail actif du temps passif de cuisson
ou d'attente. Le temps total informe l'utilisateur, tandis que la valorisation
du temps porte principalement sur le travail actif.

Les combinaisons validées peuvent définir un temps total combiné lorsqu'un
accompagnement se prépare pendant la cuisson du plat. Sans valeur curée,
Souschef utilise une somme prudente plutôt qu'un ordonnanceur complexe.

La cuisine guidée comprendra des étapes cochables, des quantités recalculées
selon les portions et des minuteries. Ouvrir une recette ne signifie pas
qu'elle a été cuisinée. À la fin du processus, l'utilisateur confirme
explicitement `Terminé` et corrige les portions si la quantité réelle diffère
du plan.

Le stock peut être réservé lors de l'acceptation du menu, mais il n'est
réellement décrémenté qu'après confirmation de la cuisson.

## Calendrier, restes et conservation

L'optimisation du pilote conserve un pool de portions non daté. Les sorties et
invités servent à calculer la demande totale, sans imposer une recette à un
jour précis.

Après la génération, l'utilisateur peut placer les repas dans son calendrier.
Souschef peut alors signaler les problèmes de conservation et suggérer de
déplacer un repas ou de congeler certaines portions, sans bloquer la décision.

Lorsqu'une recette produit plus de portions que le repas initial, l'interface
indique clairement les restes prévus. Les recettes et accompagnements possèdent
des durées de conservation curées et précisent si la congélation est possible.

L'ordre de préparation est déterminé après les achats à partir de la fraîcheur
réelle des produits. Souschef propose ce qui devrait être cuisiné en premier;
l'utilisateur choisit finalement quand cuisiner chaque repas.

La collecte exacte des dates de péremption, le traitement des produits sans
date, les notifications et la mesure du gaspillage restent à préciser lors
d'une prochaine session.

## Prix, magasins et fidélité

Le pilote commence dans une seule région avec deux enseignes contrastées :
une économique et une généraliste. Souschef utilise la localisation du ménage
pour identifier les magasins précis et estimer les déplacements, sans
conserver l'adresse complète lorsqu'elle n'est plus nécessaire.

Les prix sont rafraîchis à chaque nouvelle circulaire, normalement une fois
par semaine. Chaque rabais affiche sa période de validité et sa dernière date
de vérification. Si une collecte échoue ou produit des données incohérentes,
les anciens rabais ne sont jamais présentés comme encore actifs. Les derniers
prix réguliers connus peuvent servir d'estimations clairement signalées.

Les contrôles automatiques couvrent notamment le volume d'offres, les
variations hebdomadaires, les bornes de prix, le taux de mapping et la
comparaison à la semaine précédente.

Les prix membres publics peuvent être utilisés lorsque l'utilisateur déclare
son adhésion au programme pendant le setup. Les coupons personnels, points et
offres ciblées restent hors du premier périmètre.

Un magasin supplémentaire n'est pas ajouté par défaut lorsque son économie
nette est trop faible. Souschef présente plutôt l'option, par exemple :
« Économisez 4,20 $ de plus avec un arrêt supplémentaire ».

## Produits et substitutions

Le produit ne demande pas de préférences détaillées de marque ou de format.
Il applique toutefois une limite générale aux formats encombrants et au budget
immobilisé pour éviter des achats absurdes fondés uniquement sur le coût
unitaire.

Une substitution de marque ou de format pour le même ingrédient est permise.
La substitution d'un ingrédient par un autre reste hors périmètre.

Si le produit prévu est absent ou différent en magasin, l'utilisateur peut le
remplacer rapidement. Souschef recalcule localement le panier en préservant le
menu plutôt que de réoptimiser toutes les recettes pendant l'épicerie.

## Liste d'épicerie

La vue principale est une liste pratique à cocher, regroupée par magasin et
catégorie. Une seconde vue explique les produits, formats, rabais, prix et
économies ayant conduit à la recommandation.

Après les achats, la liste prévue est précochée. L'utilisateur corrige
seulement les absences, substitutions et quantités différentes avant la mise à
jour du stock.

## Qualité, nutrition et allergènes

Le pilote utilise un catalogue initial limité de recettes réellement testées
et validées par l'équipe Souschef. Chaque recette est normalisée et possède
des portions, quantités, temps et ingrédients fiables.

L'équilibre nutritionnel repose d'abord sur la conception des recettes et des
ensembles plat-accompagnement. Une grille éditoriale simple vérifie notamment
la présence d'une source de protéines, de légumes, d'un féculent et de
portions plausibles. Souschef ne fait pas de promesse médicale ou
nutritionnelle personnalisée pendant le pilote.

Les allergènes et restrictions obligatoires sont filtrés à partir des données
connues, mais Souschef ne garantit pas médicalement l'absence d'un allergène
dans un produit. Les informations incomplètes sont signalées et l'utilisateur
est invité à vérifier l'étiquette du produit acheté.

Il n'existe pas de filtre particulier « adapté aux enfants ». Les préférences
du ménage sont apprises à partir des réactions réelles.

## Apprentissage des préférences

Après un repas, Souschef pose une question facultative : `aimé`, `neutre` ou
`pas aimé`. En cas de rejet, l'utilisateur peut préciser s'il concerne la
recette, un ingrédient, la répétition ou l'effort de préparation.

L'utilisateur décide également si son choix vaut seulement pour cette semaine
ou doit influencer les propositions futures. Une page `Mes goûts` permet de
consulter, corriger ou effacer les préférences apprises.

Si les achats ou cuissons ne sont pas confirmés pendant plusieurs semaines,
le stock calculé devient incertain et Souschef revient progressivement au
workflow de confirmation préliminaire.

## Comptes et collaboration

L'utilisateur peut terminer le questionnaire et consulter une première
proposition avant de créer un compte. Le compte devient nécessaire pour
sauvegarder le profil, apprendre les préférences et partager le ménage.

Plusieurs membres peuvent consulter et cocher la liste synchronisée. Pendant
le pilote, un seul responsable modifie les paramètres globaux et lance les
réoptimisations.

Le produit est conçu d'abord pour téléphone. Le lancement initial vise le
Québec francophone, avec une structure de contenu permettant une traduction
anglaise ultérieure.

## Collections payantes à long terme

Souschef pourra vendre des collections permanentes associées à un thème ou à
un créateur, par exemple « 30 repas végétariens rapides ».

- Le catalogue gratuit demeure suffisamment riche pour être durablement
  utile.
- Les collections vendent de la nouveauté, de l'expertise ou une
  spécialisation, pas la correction d'un catalogue gratuit incomplet.
- Un filtre temporaire permet de planifier avec une collection achetée.
- L'optimisation normale ne favorise jamais secrètement le contenu payant.
- Avant l'achat, Souschef affiche la compatibilité de la collection avec le
  profil du ménage.
- Les contraintes obligatoires restent inviolables après l'achat.
- Toute recette payante est validée éditorialement et techniquement par
  l'équipe Souschef.
- Les achats sont permanents et liés au compte.
- Les premières collections sont produites par Souschef. Une place de marché
  de créateurs externes pourra être étudiée plus tard.
- Aucune affiliation commerciale ne doit influencer l'optimisation.

## Périmètre recommandé du premier pilote

### À construire en priorité

- questionnaire initial court et check-in hebdomadaire;
- vrais prix locaux d'une ou deux enseignes;
- catalogue curé de taille limitée;
- optimisation initiale;
- confirmation légère du garde-manger;
- périssables prioritaires ou obligatoires;
- verrouillage et remplacement de recettes;
- réoptimisation expliquée;
- liste d'épicerie finale pratique et détaillée;
- expérience mobile;
- sauvegarde et partage simple.

### À reporter

- apprentissage avancé;
- cuisine guidée complète;
- calendrier automatisé;
- import de recettes personnelles;
- comptes de fidélité et offres personnalisées;
- collections payantes;
- créateurs externes et place de marché.

## Hypothèse à valider

Avant d'élargir le produit, le pilote doit vérifier qu'un utilisateur peut
obtenir en moins de cinq minutes un menu qu'il accepte majoritairement et une
liste d'épicerie crédible à partir de vraies données.

Les métriques détaillées de validation seront définies lorsque le projet sera
prêt à organiser un pilote avec de vrais ménages.

## Questions reportées

Les sujets suivants seront repris lors d'une prochaine session :

- collecte des dates de péremption réelles après les achats;
- estimation de la conservation des produits sans date;
- confirmation post-achat et gestion des substitutions réelles;
- notifications liées à la péremption;
- mesure facultative du gaspillage réel;
- métriques et protocole du premier pilote utilisateur.
