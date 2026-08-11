"""Réduction du problème avant construction du modèle (docs/spec.md).

1. Filtres durs : allergènes, régime, équipement manquant, temps de
   préparation excessif ;
2. Troncature : conservation des 150 meilleures recettes par u_r.

Avec |R| ≈ 1000, cette étape vaut plus qu'un meilleur solveur. Les comptes
après chaque étape alimentent le rapport de diagnostic (étape 4).

Le bris de symétrie (ordre lexicographique des magasins à prix égal) relève de
la construction du modèle : étape 4.

Sémantique du filtre de temps (corrigée au point de contrôle de l'étape 3) :
``max_prep_time_per_meal_h`` est une contrainte de **session** — « je ne veux
pas passer plus de X h d'affilée en cuisine ». Une recette est exclue si même
son plus petit lot possible exige une séance trop longue :

    τ^fixe_r + β_r·τ^marg_r > plafond  →  exclue.

L'amortissement par portion (τ^fixe/β + τ^marg) promettait un confort que le
plan ne tient pas : une quiche à τ^fixe = 0,9 h et β = 8 « coûtait » 0,11 h au
filtre alors que l'utilisateur y passe réellement ~1 h d'un coup. L'arbitrage
sur le temps *moyen* appartient à κ dans l'objectif ; la valeur ajoutée du
filtre dur est précisément d'écarter les séances trop longues.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .appetence import AppetenceScorer
from .problem_data import ProfileData, RecipeData

TRUNCATION_KEEP = 150


@dataclass(frozen=True)
class PrefilterResult:
    surviving: tuple[RecipeData, ...]
    #: u_r des recettes survivantes (calculés pour la troncature ; réutilisés
    #: par le solveur sans double calcul).
    scores: dict[str, Decimal]
    #: Nombre de recettes restantes après chaque étape, dans l'ordre
    #: d'application — exigence du rapport de diagnostic.
    counts_by_stage: dict[str, int]


def prefilter_recipes(
    recipes: tuple[RecipeData, ...],
    profile: ProfileData,
    scorer: AppetenceScorer,
    truncation_keep: int = TRUNCATION_KEEP,
    force_keep_ids: frozenset[str] = frozenset(),
    exclude_ids: frozenset[str] = frozenset(),
) -> PrefilterResult:
    """``force_keep_ids``/``exclude_ids`` : verrouillage/remplacement de
    recette (pilote, docs/product-pilot.md). ``exclude_ids`` est retiré
    juste après les filtres durs — une recette exclue reste soumise aux
    mêmes garanties de sécurité si jamais reproposée plus tard, mais ne
    l'est pas ici. ``force_keep_ids`` rajoute après troncature toute
    recette qui a survécu aux filtres durs mais est tombée hors de la
    fenêtre des 150 meilleures par score — une recette verrouillée qui ne
    passerait *plus* les filtres durs (ex. nouvelle allergie déclarée entre
    deux générations) n'est **pas** repêchée : la sécurité prime sur le
    verrou, et l'appelant (``services/planning.py::reoptimize_plan``) doit
    détecter ce cas et lever une erreur explicite plutôt que de l'ignorer.
    """
    counts = {"initial": len(recipes)}

    allergens = set(profile.allergen_flags)
    step = [r for r in recipes if not (allergens & set(r.allergen_flags))]
    counts["allergenes"] = len(step)

    diet = set(profile.diet_flags)
    step = [r for r in step if diet <= set(r.diet_flags)]
    counts["regime"] = len(step)

    equipment = set(profile.available_equipment)
    step = [r for r in step if set(r.required_equipment) <= equipment]
    counts["equipement"] = len(step)

    tmax = profile.max_prep_time_per_meal_h
    step = [
        r
        for r in step
        if (r.prep_time_fixed_h
            + Decimal(r.min_batch_servings) * r.prep_time_marginal_h) <= tmax
    ]
    counts["temps_preparation"] = len(step)

    if exclude_ids:
        step = [r for r in step if r.id not in exclude_ids]
        counts["exclusion"] = len(step)

    scores = {r.id: scorer.score(r) for r in step}
    step.sort(key=lambda r: (-scores[r.id], r.id))  # départage déterministe
    kept = step[:truncation_keep]
    if force_keep_ids:
        kept_ids = {r.id for r in kept}
        kept = kept + [
            r for r in step
            if r.id in force_keep_ids and r.id not in kept_ids
        ]
    counts["troncature"] = len(kept)

    return PrefilterResult(
        surviving=tuple(kept),
        scores={r.id: scores[r.id] for r in kept},
        counts_by_stage=counts,
    )
