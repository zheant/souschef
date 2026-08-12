"""Assertions de validité — avant tout appel au solveur (docs/spec.md).

Chaque échec lève une exception **explicite**, jamais un avertissement
silencieux. La fonction retourne la liste ordonnée des assertions passées,
pour le rapport de diagnostic (en cas d'infaisabilité du solveur : « la liste
des assertions passées et le dernier drapeau activé »).

Ces assertions s'évaluent **à l'exécution contre les données chargées de la
base** (via ``load_problem_data``) : la calibration du seed garantit
l'assertion 1 par construction *au moment de la génération*, mais un vrai
scraper apportera ses vrais prix — c'est ici, à chaque résolution, que la
borne est réellement tenue.

Adaptations décidées au point de contrôle de l'étape 2 (docs/deviations.md,
D9) : la demande est un encadrement ⌈D⌉ ≤ Σx_r ≤ ⌈D(1+ε)⌉. L'assertion 6 se
teste contre la borne basse ⌈D⌉ ; la capacité entière contre la borne haute
(plafond par recette min(⌊α·⌈D(1+ε)⌉⌋, m_r)).

D17 (docs/deviations.md) : les assertions 6 et 6b comptent désormais UNE
valeur par ``dish_family_id`` (D16 : deux variantes du même plat ne peuvent
plus être actives ensemble), pas une par recette — sinon la borne basse
sous-estime le β réellement requis (le minimum global peut n'appartenir
qu'à une seule famille) et la borne haute surestime la capacité (deux
variantes d'une même famille ne s'additionnent pas, une seule est
disponible à la fois).
"""

from __future__ import annotations

import math
from decimal import Decimal

from .demand import DemandBounds, compute_demand_bounds
from .params import EffectiveParams
from .problem_data import ProblemData, RecipeData
from .units import BASE_UNIT_OF_KIND


class ValidationError(Exception):
    """Base des erreurs de validité pré-solveur."""

    assertion: str = "?"


class SalvageBoundError(ValidationError):
    assertion = "1_bornitude_recuperation"


class BatchBoundsError(ValidationError):
    assertion = "2_bornes_de_lot"


class UnitMismatchError(ValidationError):
    assertion = "3_coherence_unites"


class MissingPriceError(ValidationError):
    assertion = "4_couverture_produits"


class EmptyProblemError(ValidationError):
    assertion = "5_probleme_non_vide"


class DiversityInfeasibleError(ValidationError):
    assertion = "6_compatibilite_diversite"


class CapacityError(ValidationError):
    assertion = "6b_capacite_entiere"


def min_taxed_price_per_base_unit(
    problem: ProblemData,
) -> dict[str, Decimal]:
    """min_{p∈P_i, s} c_ps(1+t_p)/v_p par ingrédient, sur les prix valides à
    la date du problème."""
    products_by_id = {p.id: p for p in problem.products}
    best: dict[str, Decimal] = {}
    for price in problem.prices:
        prod = products_by_id[price.product_id]
        per_unit = (
            Decimal(price.price_cents_cad)
            * (1 + prod.tax_rate)
            / prod.package_qty_in_base_unit
        )
        iid = prod.canonical_ingredient_id
        if iid not in best or per_unit < best[iid]:
            best[iid] = per_unit
    return best


def validate_problem(
    problem: ProblemData,
    surviving_recipes: tuple[RecipeData, ...],
    params: EffectiveParams,
) -> tuple[list[str], DemandBounds]:
    """Exécute les assertions 1 à 6 dans l'ordre de la spec.

    ``surviving_recipes`` sont les recettes **après préfiltrage** : les
    assertions 4 à 6 se jugent sur le problème réellement soumis au solveur,
    pas sur le catalogue complet.

    ``params`` : sortie de ``resolve_effective_params`` — R_min, α et ε
    doivent être lus ici, jamais sur ``problem.profile`` directement (LA
    fonction de résolution, ``services/params.py``, l'interdit
    explicitement). Sans ça, une surcharge ``SolverConfig`` de ces trois
    paramètres serait ignorée par la validation pré-solveur tout en étant
    honorée par le solveur lui-même — les bornes de demande vérifiées ici
    divergeraient silencieusement de celles réellement construites dans le
    modèle (trouvé en écrivant un test de non-régression sans rapport,
    jamais couvert avant).

    Retourne (assertions passées, bornes de demande) ; lève à la première
    violation.
    """
    passed: list[str] = []
    profile = problem.profile

    # -- 1. Bornitude de la récupération, avec marge de sécurité ------------
    min_price = min_taxed_price_per_base_unit(problem)
    for iid, ing in problem.ingredients.items():
        sigma = ing.salvage_value_cents_per_base_unit
        if sigma is None:
            continue  # valeur métier non encore curée : aucune récupération
        if sigma == 0 or iid not in min_price:
            continue  # sans produit prixé, l'ingrédient tombe sous l'assertion 4
        bound = Decimal("0.8") * min_price[iid]
        if sigma > bound:
            raise SalvageBoundError(
                f"σ({iid}) = {sigma} cents/u.b. > 0,8·min prix taxé/u.b. = "
                f"{bound:.6f} : la récupération n'est pas bornée avec marge "
                "(risque d'optima absurdes à coût de surplus quasi nul)."
            )
    passed.append(SalvageBoundError.assertion)

    # -- 2. Bornes de lot ---------------------------------------------------
    for r in surviving_recipes:
        if r.min_batch_servings < 1:
            raise BatchBoundsError(
                f"β({r.id}) = {r.min_batch_servings} < 1 : le solveur pourrait "
                f"payer τ_fixe avec x_r = 0."
            )
        if r.max_batch_servings < r.min_batch_servings:
            raise BatchBoundsError(
                f"m({r.id}) = {r.max_batch_servings} < β = {r.min_batch_servings}."
            )
    passed.append(BatchBoundsError.assertion)

    # -- 3. Référentiel et unités -------------------------------------------
    for r in surviving_recipes:
        for ri in r.ingredients:
            ing = problem.ingredients.get(ri.canonical_ingredient_id)
            if ing is None:
                raise UnitMismatchError(
                    f"'{r.id}' référence l'ingrédient canonique inexistant "
                    f"'{ri.canonical_ingredient_id}'."
                )
            expected = BASE_UNIT_OF_KIND.get(ing.unit_kind)
            if ing.base_unit != expected:
                raise UnitMismatchError(
                    f"'{ing.id}' : base_unit '{ing.base_unit}' incompatible "
                    f"avec unit_kind '{ing.unit_kind}' (attendu '{expected}')."
                )
    passed.append(UnitMismatchError.assertion)

    # -- 4. Chaque ingrédient requis a un produit avec prix valide ----------
    required = {
        ri.canonical_ingredient_id
        for r in surviving_recipes
        for ri in r.ingredients
    }
    unpriced = sorted(required - set(min_price))
    if unpriced:
        raise MissingPriceError(
            f"Aucun produit avec prix valide au {problem.on_date} pour : "
            f"{unpriced} — infaisabilité garantie."
        )
    passed.append(MissingPriceError.assertion)

    # -- 5. Problème non vide -----------------------------------------------
    bounds = compute_demand_bounds(
        profile.meals_per_horizon,
        list(profile.appetite_coefficients),
        Decimal(str(params.demand_slack_epsilon.value)),
    )
    if bounds.exact <= 0:
        raise EmptyProblemError(f"D = {bounds.exact} ≤ 0.")
    if not problem.stores:
        raise EmptyProblemError("Aucun magasin.")
    if not surviving_recipes:
        raise EmptyProblemError("Aucune recette après préfiltrage.")
    passed.append(EmptyProblemError.assertion)

    # -- 6. Compatibilité des contraintes de diversité ----------------------
    # D17 : une seule valeur de β par famille de plat (la plus petite de ses
    # variantes survivantes), pas R_min fois le minimum GLOBAL — ce minimum
    # peut n'appartenir qu'à une seule famille, auquel cas les R_min-1 autres
    # plats distincts nécessaires ne peuvent pas tous l'atteindre.
    r_min = params.min_distinct_recipes.value
    alpha = Decimal(str(params.max_share_per_recipe.value))
    family_min_beta: dict[str, int] = {}
    for r in surviving_recipes:
        fam = r.dish_family_id
        if fam not in family_min_beta or r.min_batch_servings < family_min_beta[fam]:
            family_min_beta[fam] = r.min_batch_servings

    if len(family_min_beta) < r_min:
        raise DiversityInfeasibleError(
            f"{len(family_min_beta)} famille(s) de plat disponible(s) après "
            f"préfiltrage < R_min = {r_min} : impossible d'atteindre R_min "
            "plats distincts, même sans contrainte de portions (D16 : deux "
            "variantes du même plat ne comptent que pour une famille)."
        )

    smallest_betas = sorted(family_min_beta.values())[:r_min]
    needed = sum(smallest_betas)
    if needed > bounds.low:  # borne basse ⌈D⌉ (D9)
        raise DiversityInfeasibleError(
            f"Somme des {r_min} plus petits β_r (une valeur par famille de "
            f"plat) = {smallest_betas} = {needed} > ⌈D⌉ = {bounds.low} : "
            "infaisabilité arithmétique que le message du solveur ne "
            "révélera pas."
        )
    if r_min < math.ceil(1 / alpha):  # ≥ requis — l'égalité est valide
        raise DiversityInfeasibleError(
            f"R_min = {r_min} < ⌈1/α⌉ = {math.ceil(1 / alpha)} : la part "
            f"maximale α = {alpha} exige plus de recettes distinctes."
        )
    passed.append(DiversityInfeasibleError.assertion)

    # -- 6b. Capacité entière contre la borne haute (D9) --------------------
    # D17 : même biais, en miroir — sommer min(cap, m_r) sur TOUTES les
    # recettes survivantes double-compte la capacité d'une famille à deux
    # variantes (D16 : une seule peut être active à la fois). Une seule
    # valeur par famille : la plus généreuse de ses variantes (celle qu'on
    # choisirait réellement), pas la somme des deux.
    per_recipe_cap = math.floor(alpha * bounds.high)
    family_capacity: dict[str, int] = {}
    for r in surviving_recipes:
        fam = r.dish_family_id
        cap = min(per_recipe_cap, r.max_batch_servings)
        if fam not in family_capacity or cap > family_capacity[fam]:
            family_capacity[fam] = cap
    capacity = sum(family_capacity.values())
    if capacity < bounds.low:
        raise CapacityError(
            f"Capacité entière Σ_familles max(min(⌊α·⌈D(1+ε)⌉⌋, m_r)) = "
            f"{capacity} < ⌈D⌉ = {bounds.low} : la demande minimale est hors "
            "d'atteinte."
        )
    passed.append(CapacityError.assertion)

    return passed, bounds
