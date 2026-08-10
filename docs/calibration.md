# Analyse de calibration — κ et u_r (point de contrôle de l'étape 4)

Exigée avant l'étape 5 : les plans que l'API persistera dépendent de cette
calibration. Configuration : seed principal, tous drapeaux actifs,
`mip_gap = 0,002`. κ du profil de seed : 1500 cents/h = **15 $/h**.

## Sensibilité à κ ∈ {0, 5, 10, 15, 20} $/h

| κ | recettes | portions | magasin | achats | dépl. | temps | récup. | appét. | total | heures |
|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 0 $ | 8 | 41 | marche_central | 26,38 | 8,80 | 0,00 | 2,58 | 63,96 | −31,35 | 4,71 |
| 5 $ | 6 | 40 | marche_central | 24,18 | 8,80 | 19,62 | 2,47 | 58,84 | −8,70 | 3,92 |
| 10 $ | 5 | 37 | marche_central | 27,13 | 8,80 | 33,05 | 3,13 | 56,84 | 9,01 | 3,31 |
| 15 $ | 4 | 37 | marche_central | 27,13 | 8,80 | 45,98 | 3,07 | 53,80 | 25,04 | 3,06 |
| 20 $ | 4 | 37 | marche_central | 27,13 | 8,80 | 61,30 | 3,07 | 53,80 | 40,36 | 3,06 |

**Note sur le plateau** : la solution se stabilise dès κ = 15 $/h — le
profil de seed est au **début du plateau**, pas au milieu de la zone sensible.
Conséquence pratique : si κ est un jour inféré par sondage plutôt que déclaré,
la plage discriminante est **0–15 $/h** ; des questions d'arbitrage au-delà ne
départageront rien.

**Verdict : arbitrage, pas interrupteur.** La solution varie continûment et
monotonement : 8 → 6 → 5 → 4 recettes, 41 → 40 → 37 portions, 4,71 → 3,06 h,
avec un menu différent à chaque palier jusqu'à κ = 15 (stabilisation
15 → 20). Mécanisme lisible : κ croissant élimine d'abord les petites
recettes qui paient un τ^fixe peu amorti (les formats familiaux gagnent),
puis les portions marginales dont le 3e segment d'utilité (35 % de u_r) ne
couvre plus κ·τ^marg. Le niveau élevé du terme (46 $ = 3,06 h × 15 $/h) est
le **niveau**, réaliste pour 14 repas cuisinés ; c'est le **gradient** qui
arbitre, et il arbitre.

**Pourquoi le magasin ne bouge pas avec κ.** Le terme de temps est séparable :
il dépend de x_r, pas de n_ps. Les 46 $ ne pèsent pas sur l'axe magasin ;
cet axe se joue entre achats et déplacements (voir ci-dessous).

## Arbitrage de magasin (κ = 15, magasin imposé)

| magasin imposé | achats | objectif hors déplacements | déplacements si choisi |
|---|---:|---:|---:|
| marche_central | 27,13 | 16,23 | 8,81 |
| maxiprix_lebourgneuf | 27,01 | 15,96 | 13,99 |
| epicier_du_coin | 30,39 | 25,18 | 6,59 |

Sur le menu optimal (végétal : lentilles, riz, tofu, œufs), les promos de la
semaine ramènent le panier Maxi-Prix à 0,12 $ du Marché Central : l'avantage
de bannière ne couvre pas les 5,19 $ de déplacement supplémentaires, et le
Marché gagne de ~5 $. L'Épicier du Coin, pourtant le plus proche, perd de
~7 $ : assortiment et prix dominent la distance. Le choix de magasin est bien
piloté par les prix contre les déplacements, avec des marges de l'ordre de
grandeur des promos hebdomadaires — il basculera selon les circulaires.

## Sensibilité à u_r (mise à l'échelle ±10 %, κ = 15)

| facteur | recettes | portions | appétence | total | menu |
|---:|---:|---:|---:|---:|---|
| ×0,90 | 4 | 37 | 48,43 | 30,41 | identique |
| ×1,00 | 4 | 37 | 53,80 | 25,04 | riz_frit_familial×11, chili_lentilles_familial×10, sauté_tofu_familial×8, chili_lentilles×8 |
| ×1,10 | 4 | 37 | 59,18 | 19,66 | identique |

**Verdict : ensemble ET allocation strictement invariants à ±10 %.**
L'appétence est un grand terme en *niveau* (37 portions × ~1,45 $ moyen) mais
son écart *entre solutions candidates* est petit : elle sélectionne le peloton
de tête (via la troncature et l'ordre), puis prix et temps arbitrent les
marges. Une reformulation du scorer déplacerait le niveau, pas le plan — le
modèle est plus sensible aux rabais réels qu'à la calibration du scorer, ce
qui est le produit voulu.

## Conclusion

Aucune recalibration du seed nécessaire. Les deux critères d'alerte du point
de contrôle (terme-interrupteur, hypersensibilité au scorer) sont écartés par
les données. Outillage pérennisé : le scorer est désormais injecté dans le
solveur (`PulpMenuSolver(scorer_factory=…)`), ce qui a corrigé au passage un
défaut d'interface (le RuleBased était codé en dur, contredisant la
remplaçabilité voulue par la spec) et rend cette analyse rejouable.
