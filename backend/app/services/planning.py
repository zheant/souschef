"""``PlanningModule`` — génération, consultation et commit d'un plan.

Le solveur, comme le scorer, est **injecté** : brancher une autre
implémentation (HiGHS, modèle appris, faux de test) ne touche ni ce module,
ni l'API, ni le front-end.

Interface publique (``docs/architecture-refactoring-plan.md``) :
``generate_plan`` / ``get_plan`` / ``commit_plan``. Chaque fonction garde
``session: Session`` en premier paramètre explicite — pas de session ouverte
en interne : ``tests/db_fixtures.py::api_client`` override la dépendance
FastAPI ``get_session`` pour injecter une session de test partagée, et
n'a aucune prise sur une session que ce module ouvrirait lui-même. Les routes
transmettent la session sans jamais l'utiliser pour une requête — c'est la
règle réelle de ``CLAUDE.md`` (« l'API ne touche jamais SQLAlchemy
directement pour de la logique métier »), pas la formulation littérale du
document de refactor source.

Le ``commit`` est ce qui rend le terme de récupération honnête (docs/spec.md,
section API) : il décrémente le stock consommé et reporte les restes vers
``pantry_stock``. Les recettes des derniers plans commis alimentent la
pénalité de répétition du scoring d'appétence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import (
    CanonicalIngredient, PantryPriority, PantryStock, Plan, PlanStatus, Product,
    Recipe,
)
from ..models.base import utcnow
from ..services.appetence import RuleBasedAppetenceScorer
from ..services.prefilter import prefilter_recipes
from ..services.needs import ingredient_needs
from ..services.problem_data import load_problem_data
from ..solver.config import SolverConfig
from ..solver.port import MenuSolver, SolveResult

#: Nombre de plans commis récents alimentant la pénalité de répétition
#: (aligné sur les deux niveaux de pénalité du scorer).
RECENT_PLANS_FOR_REPETITION = 2


class PlanNotFound(LookupError):
    """Aucun plan avec cet id pour ce profil (l'API traduit en 404)."""


class PlanNotCommittable(ValueError):
    """Le plan n'est pas dans un état commitable (l'API traduit en 409)."""


class RecipeNotInPlanError(LookupError):
    """Verrouillage demandé sur une recette absente du plan précédent
    (l'API traduit en 404)."""


class RecipeNotLockableError(ValueError):
    """Recette verrouillée disparue du préfiltrage — ex. nouvelle allergie
    déclarée entre deux générations (l'API traduit en 422)."""


class PantryIngredientNotUsableError(ValueError):
    """Un ingrédient marqué « doit être utilisé » n'apparaît dans aucune
    recette du catalogue (l'API traduit en 422)."""


class ConflictingRecipeSelectionError(ValueError):
    """Une recette à la fois verrouillée et exclue (l'API traduit en 422)."""


class PlanAlreadyCommittedError(ValueError):
    """Un plan déjà commis ne peut plus être réoptimisé (verrouiller/
    remplacer une recette) — le stock du garde-manger et les achats ont
    déjà été ajustés pour le menu tel qu'accepté ; le modifier après coup
    désynchroniserait cette comptabilité du menu réellement suivi (l'API
    traduit en 409)."""


@dataclass(frozen=True)
class MenuLine:
    recipe_id: str
    name: str
    servings: int
    prep_time_h: str
    attributed_cost_cents_cad: str


@dataclass(frozen=True)
class PlanPantryLine:
    """Garde-manger itemisé pour l'écran Résultat (pilote,
    docs/product-pilot.md) — ``diagnostic.pantry_consumed_by_ingredient``
    existe depuis l'étape 5 (id → quantité/valeur) mais n'était résolu en nom
    nulle part, contrairement aux lignes d'achat (``_grocery_list``)."""

    canonical_ingredient_id: str
    name: str
    quantity_base_unit: str
    base_unit: str
    priority: str


@dataclass(frozen=True)
class PlanView:
    id: int
    status: str
    solver_status: str
    on_date: date
    menu: list[MenuLine]
    #: Groupée par magasin ; structure documentée dans docs/spec.md (section
    #: API), pas re-typée ici — même choix que ``diagnostic`` ci-dessous.
    grocery_list_by_store: list[dict]
    pantry_lines: list[PlanPantryLine]
    stores_visited: list[str]
    diagnostic: dict


@dataclass(frozen=True)
class CommitResult:
    plan_id: int
    status: str
    pantry_after_commit: dict[str, str]


@dataclass(frozen=True)
class MenuChange:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    #: Poste « achats » du nouveau plan moins celui de l'ancien (positif =
    #: coûte plus cher).
    cost_delta_cents: str


@dataclass(frozen=True)
class ReoptimizationResult:
    plan: PlanView
    #: None si le nouveau plan est infaisable — le diagnostic d'infaisabilité
    #: porte déjà l'explication (même convention que l'écran Génération).
    changes: MenuChange | None


def recent_committed_recipe_ids(
    session: Session, profile_id: str, limit: int = RECENT_PLANS_FOR_REPETITION
) -> tuple[tuple[str, ...], ...]:
    plans = session.scalars(
        select(Plan)
        .where(
            Plan.household_profile_id == profile_id,
            Plan.status == PlanStatus.committed,
        )
        .order_by(Plan.committed_at.desc())
        .limit(limit)
    ).all()
    return tuple(tuple(p.servings.keys()) for p in plans)


def generate_plan(
    session: Session,
    profile_id: str,
    on_date: date,
    config: SolverConfig,
    solver: MenuSolver,
) -> PlanView:
    problem = load_problem_data(session, profile_id, on_date)
    pre = _run_prefilter(session, profile_id, problem)
    config = _with_must_use_pantry(session, profile_id, problem, config)
    result = solver.solve(problem, pre, config)
    plan = _persist_plan(session, profile_id, on_date, config, problem, result)
    return _plan_view(session, plan)


def reoptimize_plan(
    session: Session,
    profile_id: str,
    plan_id: int,
    locked_recipe_ids: frozenset[str],
    excluded_recipe_ids: frozenset[str],
    config: SolverConfig,
    solver: MenuSolver,
) -> ReoptimizationResult:
    """Verrouillage/remplacement de recette (pilote, docs/product-pilot.md) —
    un seul mécanisme sert les deux usages : « remplacer » = verrouiller
    toutes les autres recettes du plan + exclure la recette visée (et ses
    variantes d'échelle sœurs, D16) ; « réoptimisation plus large » = même
    appel avec seulement les recettes explicitement verrouillées par
    l'utilisateur. C'est à l'appelant (l'API) de construire ces deux
    ensembles différemment — pas à ce module.
    """
    previous = _load_owned_plan(session, profile_id, plan_id)
    if previous.status == PlanStatus.committed:
        raise PlanAlreadyCommittedError(
            f"Plan {plan_id} déjà commis : le menu ne peut plus être modifié."
        )

    if not locked_recipe_ids <= previous.servings.keys():
        missing = locked_recipe_ids - previous.servings.keys()
        raise RecipeNotInPlanError(
            f"Recette(s) absente(s) du plan {plan_id} : {sorted(missing)}."
        )
    if locked_recipe_ids & excluded_recipe_ids:
        raise ConflictingRecipeSelectionError(
            "Recette(s) à la fois verrouillée(s) et exclue(s) : "
            f"{sorted(locked_recipe_ids & excluded_recipe_ids)}."
        )

    problem = load_problem_data(session, profile_id, previous.on_date)
    # Exclure une recette exclut aussi ses variantes d'échelle sœurs (D16) :
    # remplacer un plat ne doit pas simplement resservir l'autre format du
    # même plat — l'exclusion mutuelle de variantes au solveur ne protège
    # que les recettes qui restent candidates, pas celles écartées ici, en
    # amont, au préfiltrage.
    excluded_families = {
        r.dish_family_id for r in problem.recipes if r.id in excluded_recipe_ids
    }
    full_excluded_ids = frozenset(excluded_recipe_ids) | {
        r.id for r in problem.recipes if r.dish_family_id in excluded_families
    }

    pre = _run_prefilter(
        session, profile_id, problem,
        force_keep_ids=locked_recipe_ids, exclude_ids=full_excluded_ids,
    )
    # Erreur explicite AVANT le solveur (jamais un statut Infeasible muet) :
    # une recette verrouillée qui ne survit plus au préfiltrage (ex.
    # nouvelle allergie déclarée entre deux générations) n'est pas repêchée
    # par force_keep_ids (services/prefilter.py) — c'est ici qu'on le détecte.
    surviving_ids = {r.id for r in pre.surviving}
    if not locked_recipe_ids <= surviving_ids:
        raise RecipeNotLockableError(
            "Recette(s) verrouillée(s) ne passant plus les filtres du "
            "profil actuel (allergènes/régime/équipement/temps) : "
            f"{sorted(locked_recipe_ids - surviving_ids)}."
        )

    locked_recipe_servings = {
        rid: previous.servings[rid] for rid in locked_recipe_ids
    }
    reopt_config = config.model_copy(
        update={"locked_recipe_servings": locked_recipe_servings}
    )
    reopt_config = _with_must_use_pantry(session, profile_id, problem, reopt_config)
    result = solver.solve(problem, pre, reopt_config)
    plan = _persist_plan(
        session, profile_id, previous.on_date, reopt_config, problem, result
    )

    view = _plan_view(session, plan)
    changes = None
    if result.status == "Optimal":
        old_ids = set(previous.servings.keys())
        new_ids = set(plan.servings.keys())
        old_achats = Decimal(previous.diagnostic["objective_terms_cents"]["achats"])
        new_achats = Decimal(plan.diagnostic["objective_terms_cents"]["achats"])
        changes = MenuChange(
            added=tuple(sorted(new_ids - old_ids)),
            removed=tuple(sorted(old_ids - new_ids)),
            cost_delta_cents=str(new_achats - old_achats),
        )
    return ReoptimizationResult(plan=view, changes=changes)


def get_plan(session: Session, profile_id: str, plan_id: int) -> PlanView:
    return _plan_view(session, _load_owned_plan(session, profile_id, plan_id))


def commit_plan(session: Session, profile_id: str, plan_id: int) -> CommitResult:
    plan = _load_owned_plan(session, profile_id, plan_id)
    new_stock = _apply_commit(session, plan)
    return CommitResult(
        plan_id=plan.id, status=plan.status.value, pantry_after_commit=new_stock
    )


def _load_owned_plan(session: Session, profile_id: str, plan_id: int) -> Plan:
    plan = session.get(Plan, plan_id)
    if plan is None or plan.household_profile_id != profile_id:
        raise PlanNotFound(f"Plan {plan_id} introuvable.")
    return plan


def _run_prefilter(
    session: Session,
    profile_id: str,
    problem,
    force_keep_ids: frozenset[str] = frozenset(),
    exclude_ids: frozenset[str] = frozenset(),
):
    recent = recent_committed_recipe_ids(session, profile_id)
    scorer = RuleBasedAppetenceScorer(problem, recent_recipe_ids=recent)
    return prefilter_recipes(
        problem.recipes, problem.profile, scorer,
        force_keep_ids=force_keep_ids, exclude_ids=exclude_ids,
    )


def _with_must_use_pantry(
    session: Session, profile_id: str, problem, config: SolverConfig
) -> SolverConfig:
    """Périssables obligatoires (pilote, docs/product-pilot.md) : dérive
    ``SolverConfig.must_use_pantry_ids`` depuis ``pantry_stock.priority`` —
    jamais fourni à la main par l'appelant HTTP, même motif que
    ``locked_recipe_servings``. Sans effet si ``enable_pantry_stock`` est
    inactif (cohérent avec la garde de ``_add_must_use_pantry`` côté
    solveur)."""
    if not config.enable_pantry_stock:
        return config
    ids = tuple(session.scalars(
        select(PantryStock.canonical_ingredient_id).where(
            PantryStock.household_profile_id == profile_id,
            PantryStock.priority == PantryPriority.must_use,
        )
    ).all())
    if not ids:
        return config
    # Erreur explicite AVANT le solveur (jamais un statut Infeasible muet,
    # même principe que RecipeNotLockableError) : un ingrédient « doit être
    # utilisé » qu'aucune recette ne référence ne peut jamais être satisfait.
    used_ids = {
        ri.canonical_ingredient_id for r in problem.recipes for ri in r.ingredients
    }
    unusable = sorted(iid for iid in ids if iid not in used_ids)
    if unusable:
        raise PantryIngredientNotUsableError(
            "Ingrédient(s) marqué(s) « doit être utilisé » sans aucune "
            f"recette compatible dans le catalogue : {unusable}."
        )
    return config.model_copy(update={"must_use_pantry_ids": ids})


def _persist_plan(
    session: Session,
    profile_id: str,
    on_date: date,
    config: SolverConfig,
    problem,
    result: SolveResult,
) -> Plan:
    needs = (
        ingredient_needs(
            problem, result.servings_by_recipe, result.cooked_flags,
            include_fixed=config.enable_batch_fixed_cost,
        )
        if result.status == "Optimal"
        else {}
    )
    plan = Plan(
        household_profile_id=profile_id,
        status=PlanStatus.proposed,
        on_date=on_date,
        solver_status=result.status,
        config=config.model_dump(),
        servings=result.servings_by_recipe,
        cooked={k: bool(v) for k, v in result.cooked_flags.items()},
        purchases=[
            {
                "product_id": line.product_id,
                "product_external_key": line.product_external_key,
                "store_id": line.store_id,
                "store_external_key": line.store_external_key,
                "units": line.units,
                "unit_price_cents_cad": line.unit_price_cents_cad,
                "taxed_total_cents_cad": str(line.taxed_total_cents_cad),
                "is_promo": line.is_promo,
                "regular_price_cents_cad": line.regular_price_cents_cad,
            }
            for line in result.purchases
        ],
        ingredient_needs={k: str(v) for k, v in needs.items()},
        stores_visited=list(result.stores_visited),
        diagnostic=_diagnostic_json(result),
    )
    session.add(plan)
    session.flush()
    return plan


def _diagnostic_json(result: SolveResult) -> dict:
    d = result.diagnostic
    t = d.objective_terms
    return {
        "solver_status": d.solver_status,
        "solve_time_s": d.solve_time_s,
        "mip_gap_requested": d.mip_gap_requested,
        "mip_gap_attained": d.mip_gap_attained,
        "objective_terms_cents": (
            {
                "achats": str(t.achats_cents),
                "deplacements": str(t.deplacements_cents),
                "temps": str(t.temps_cents),
                "recuperation": str(t.recuperation_cents),
                "appetence": str(t.appetence_cents),
                "total": str(t.total_cents()),
            }
            if t else None
        ),
        "effective_params": d.effective_params,
        "flag_effects": d.flag_effects,
        "saturated_constraints": d.saturated_constraints,
        "prefilter_counts": d.prefilter_counts,
        "surplus_by_ingredient": d.surplus_by_ingredient,
        "pantry_consumed_by_ingredient": d.pantry_consumed_by_ingredient,
        "pantry_consumed_value_cents": str(d.pantry_consumed_value_cents),
        "distinct_recipes": d.distinct_recipes,
        "max_share_of_demand": (
            str(d.max_share_of_demand) if d.max_share_of_demand is not None else None
        ),
        "demand": d.demand,
        "assertions_passed": d.assertions_passed,
        "last_enabled_flag": d.last_enabled_flag,
        "infeasibility_note": d.infeasibility_note,
    }


def _plan_view(session: Session, plan: Plan) -> PlanView:
    recipes = {
        r.id: r
        for r in session.scalars(
            select(Recipe).where(Recipe.id.in_(list(plan.servings.keys())))
        )
    }
    total_cents = sum(
        (Decimal(l["taxed_total_cents_cad"]) for l in plan.purchases), Decimal(0)
    )
    total_servings = sum(plan.servings.values()) or 1
    menu = []
    for rid, x in sorted(plan.servings.items(), key=lambda kv: -kv[1]):
        r = recipes[rid]
        prep = r.prep_time_fixed_h + r.prep_time_marginal_h * x
        # Coût attribué : part des achats au prorata des portions (lecture
        # simple pour l'écran Résultat ; la vraie décomposition est dans le
        # diagnostic).
        attributed = (total_cents * x / total_servings).quantize(Decimal("0.01"))
        menu.append(
            MenuLine(
                recipe_id=rid, name=r.name, servings=x,
                prep_time_h=str(prep),
                attributed_cost_cents_cad=str(attributed),
            )
        )
    return PlanView(
        id=plan.id, status=plan.status.value, solver_status=plan.solver_status,
        on_date=plan.on_date, menu=menu,
        grocery_list_by_store=_grocery_list(session, plan),
        pantry_lines=_plan_pantry_lines(session, plan),
        stores_visited=plan.stores_visited, diagnostic=plan.diagnostic,
    )


def _grocery_list(session: Session, plan: Plan) -> list[dict]:
    """Liste d'épicerie groupée par magasin. Chaque ligne : nom de
    l'ingrédient canonique, marque/produit, quantité, prix unitaire, prix
    total taxé, et les recettes qui la consomment (celles du menu utilisant
    l'ingrédient canonique du produit). ``brand``/``package_unit`` seuls ne
    disent pas *quel* aliment c'est (« Great Value, 900 g » sans plus de
    contexte) — ``ingredient_name`` porte le type de produit."""
    product_ids = {p["product_id"] for p in plan.purchases}
    products = {
        p.id: p
        for p in session.scalars(select(Product).where(Product.id.in_(product_ids)))
    }
    ingredient_names = {
        i.id: i.name
        for i in session.scalars(
            select(CanonicalIngredient).where(
                CanonicalIngredient.id.in_(
                    {p.canonical_ingredient_id for p in products.values()}
                )
            )
        )
    }
    recipe_names = {
        r.id: r.name
        for r in session.scalars(
            select(Recipe).where(Recipe.id.in_(list(plan.servings.keys())))
        )
    }
    consumers: dict[str, list[str]] = {}
    for r in session.scalars(
        select(Recipe).where(Recipe.id.in_(list(plan.servings.keys())))
    ):
        for ri in r.ingredients:
            consumers.setdefault(ri.canonical_ingredient_id, []).append(
                recipe_names[r.id]
            )

    by_store: dict[str, dict] = {}
    for line in plan.purchases:
        prod = products[line["product_id"]]
        store = by_store.setdefault(
            line["store_external_key"],
            {"store_external_key": line["store_external_key"],
             "lines": [], "subtotal_cents_cad": Decimal(0),
             "savings_cents_cad": Decimal(0)},
        )
        taxed = Decimal(line["taxed_total_cents_cad"])

        # Rabais et économies (pilote, docs/product-pilot.md) : référence
        # honnête = prix régulier du même produit, jamais une valeur
        # inventée. .get(...) : plans persistés avant ce chantier n'ont pas
        # ces clés dans leur JSONB figé — défaut sûr, pas de migration/
        # backfill nécessaire pour une donnée qui n'existait pas encore.
        is_promo = line.get("is_promo", False)
        regular = line.get("regular_price_cents_cad")
        savings = None
        if is_promo and regular is not None:
            delta = Decimal(regular) - Decimal(line["unit_price_cents_cad"])
            if delta > 0:
                savings = (
                    delta * line["units"] * (1 + prod.tax_rate)
                ).quantize(Decimal("0.01"))

        store["lines"].append({
            "product_external_key": line["product_external_key"],
            "ingredient_name": ingredient_names[prod.canonical_ingredient_id],
            "brand": prod.brand,
            "package_unit": prod.package_unit,
            "units": line["units"],
            "unit_price_cents_cad": line["unit_price_cents_cad"],
            "taxed_total_cents_cad": str(taxed),
            "consumed_by": sorted(set(consumers.get(prod.canonical_ingredient_id, []))),
            "is_promo": is_promo,
            "regular_price_cents_cad": regular,
            "savings_cents_cad": str(savings) if savings is not None else None,
        })
        store["subtotal_cents_cad"] += taxed
        if savings is not None:
            store["savings_cents_cad"] += savings
    return [
        {
            **s,
            "subtotal_cents_cad": str(s["subtotal_cents_cad"]),
            "savings_cents_cad": str(s["savings_cents_cad"]),
        }
        for s in by_store.values()
    ]


def _plan_pantry_lines(session: Session, plan: Plan) -> list[PlanPantryLine]:
    """Garde-manger itemisé (pilote, docs/product-pilot.md) : joint
    ``diagnostic.pantry_consumed_by_ingredient`` (id → quantité/valeur,
    présent depuis l'étape 5) contre ``CanonicalIngredient`` pour le nom —
    même pattern que ``_grocery_list`` pour les achats — et contre
    ``PantryStock.priority`` pour distinguer les périssables prioritaires
    (D « Périssables prioritaires ou obligatoires »)."""
    consumed: dict[str, dict] = plan.diagnostic.get("pantry_consumed_by_ingredient") or {}
    ids = [
        iid for iid, v in consumed.items()
        if Decimal(v["quantite_base_unit"]) > 0
    ]
    if not ids:
        return []
    ingredients = {
        i.id: i
        for i in session.scalars(
            select(CanonicalIngredient).where(CanonicalIngredient.id.in_(ids))
        )
    }
    priorities = {
        ps.canonical_ingredient_id: ps.priority
        for ps in session.scalars(
            select(PantryStock).where(
                PantryStock.household_profile_id == plan.household_profile_id,
                PantryStock.canonical_ingredient_id.in_(ids),
            )
        )
    }
    return [
        PlanPantryLine(
            canonical_ingredient_id=iid,
            name=ingredients[iid].name,
            quantity_base_unit=consumed[iid]["quantite_base_unit"],
            base_unit=ingredients[iid].base_unit,
            priority=priorities.get(iid, PantryPriority.normal).value,
        )
        for iid in sorted(ids)
    ]


def _purchased_by_ingredient(
    session: Session, purchases: list[dict]
) -> dict[str, Decimal]:
    """Quantité totale déjà achetée par ingrédient canonique (base_unit),
    depuis des lignes d'achat sérialisées — factoré parce que
    ``_apply_commit`` en a besoin deux fois : une fois avant d'ajouter les
    lignes « à acheter » (pour calculer ce qui manque réellement), une fois
    après (pour la comptabilité finale du stock)."""
    if not purchases:
        return {}
    products = {
        p.id: p
        for p in session.scalars(
            select(Product).where(
                Product.id.in_({l["product_id"] for l in purchases})
            )
        )
    }
    result: dict[str, Decimal] = {}
    for line in purchases:
        prod = products[line["product_id"]]
        result[prod.canonical_ingredient_id] = (
            result.get(prod.canonical_ingredient_id, Decimal(0))
            + prod.package_qty_in_base_unit * line["units"]
        )
    return result


def _apply_commit(session: Session, plan: Plan) -> dict[str, str]:
    """Décrémente le stock consommé et reporte les restes vers pantry_stock.

    Comptabilité par ingrédient (déterministe depuis les données figées du
    plan) : acheté = Σ unités·v_p ; consommé du garde-manger =
    min(stock, besoin) si le plan a utilisé le stock, 0 sinon ; nouveau stock
    = (stock − consommé) + (acheté + consommé − besoin). Le second terme est
    exactement le w_i du solveur quand la récupération était active — c'est ce
    report qui rend σ_i honnête : la valeur résiduelle promise est réalisée.

    Correction d'un ingrédient déclaré à tort au garde-manger (« à
    acheter ») : ce n'est **plus** géré ici. Une tentative de le corriger au
    moment du commit (résoudre un achat de remplacement après coup) s'est
    avérée fragile en pratique — double-achat, quantités qui ne collaient
    jamais exactement à ce qu'un vrai panier optimal aurait choisi. La bonne
    correction, plus solide, se fait *avant* le commit : mettre
    ``pantry_stock`` à 0 pour l'ingrédient concerné puis relancer une vraie
    réoptimisation (``reoptimize_plan``) — le solveur, pas une heuristique
    séparée, décide alors du panier réellement optimal. Voir Result.tsx
    (« Replanifier ») et CLAUDE.md pour l'historique de cette décision.
    """
    if plan.status != PlanStatus.proposed:
        raise PlanNotCommittable(f"Plan {plan.id} déjà '{plan.status.value}'.")
    if plan.solver_status != "Optimal":
        raise PlanNotCommittable(
            f"Plan {plan.id} non commis : statut solveur '{plan.solver_status}'."
        )

    purchased = _purchased_by_ingredient(session, plan.purchases)

    pantry = {
        ps.canonical_ingredient_id: ps
        for ps in session.scalars(
            select(PantryStock).where(
                PantryStock.household_profile_id == plan.household_profile_id
            )
        )
    }
    used_pantry = bool(plan.config.get("enable_pantry_stock"))
    new_stock: dict[str, str] = {}
    for iid in sorted(set(purchased) | set(plan.ingredient_needs)):
        need = Decimal(plan.ingredient_needs.get(iid, "0"))
        bought = purchased.get(iid, Decimal(0))
        stock = pantry[iid].quantity_base_unit if iid in pantry else Decimal(0)
        consumed = min(stock, need) if used_pantry else Decimal(0)
        leftover = bought + consumed - need
        if leftover < 0:
            raise PlanNotCommittable(
                f"Plan {plan.id} incohérent : besoin de {iid} non couvert "
                f"({bought}+{consumed} < {need})."
            )
        qty = (stock - consumed) + leftover
        stmt = (
            pg_insert(PantryStock)
            .values(
                household_profile_id=plan.household_profile_id,
                canonical_ingredient_id=iid,
                quantity_base_unit=qty,
            )
            .on_conflict_do_update(
                index_elements=["household_profile_id", "canonical_ingredient_id"],
                set_={"quantity_base_unit": qty},
            )
        )
        session.execute(stmt)
        new_stock[iid] = str(qty)

    plan.status = PlanStatus.committed
    plan.committed_at = utcnow()
    session.flush()
    return new_stock
