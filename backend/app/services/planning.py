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

from ..models import PantryStock, Plan, PlanStatus, Product, Recipe
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


@dataclass(frozen=True)
class MenuLine:
    recipe_id: str
    name: str
    servings: int
    prep_time_h: str
    attributed_cost_cents_cad: str


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
    stores_visited: list[str]
    diagnostic: dict


@dataclass(frozen=True)
class CommitResult:
    plan_id: int
    status: str
    pantry_after_commit: dict[str, str]


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
    plan, _ = _solve_and_persist(session, profile_id, on_date, config, solver)
    return _plan_view(session, plan)


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


def _solve_and_persist(
    session: Session,
    profile_id: str,
    on_date: date,
    config: SolverConfig,
    solver: MenuSolver,
) -> tuple[Plan, SolveResult]:
    problem = load_problem_data(session, profile_id, on_date)
    recent = recent_committed_recipe_ids(session, profile_id)
    scorer = RuleBasedAppetenceScorer(problem, recent_recipe_ids=recent)
    pre = prefilter_recipes(problem.recipes, problem.profile, scorer)
    result = solver.solve(problem, pre, config)

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
            }
            for line in result.purchases
        ],
        ingredient_needs={k: str(v) for k, v in needs.items()},
        stores_visited=list(result.stores_visited),
        diagnostic=_diagnostic_json(result),
    )
    session.add(plan)
    session.flush()
    return plan, result


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
        stores_visited=plan.stores_visited, diagnostic=plan.diagnostic,
    )


def _grocery_list(session: Session, plan: Plan) -> list[dict]:
    """Liste d'épicerie groupée par magasin. Chaque ligne : produit, quantité,
    prix unitaire, prix total taxé, et les recettes qui la consomment (celles
    du menu utilisant l'ingrédient canonique du produit)."""
    product_ids = {p["product_id"] for p in plan.purchases}
    products = {
        p.id: p
        for p in session.scalars(select(Product).where(Product.id.in_(product_ids)))
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
             "lines": [], "subtotal_cents_cad": Decimal(0)},
        )
        taxed = Decimal(line["taxed_total_cents_cad"])
        store["lines"].append({
            "product_external_key": line["product_external_key"],
            "brand": prod.brand,
            "package_unit": prod.package_unit,
            "units": line["units"],
            "unit_price_cents_cad": line["unit_price_cents_cad"],
            "taxed_total_cents_cad": str(taxed),
            "consumed_by": sorted(set(consumers.get(prod.canonical_ingredient_id, []))),
        })
        store["subtotal_cents_cad"] += taxed
    return [
        {**s, "subtotal_cents_cad": str(s["subtotal_cents_cad"])}
        for s in by_store.values()
    ]


def _apply_commit(session: Session, plan: Plan) -> dict[str, str]:
    """Décrémente le stock consommé et reporte les restes vers pantry_stock.

    Comptabilité par ingrédient (déterministe depuis les données figées du
    plan) : acheté = Σ unités·v_p ; consommé du garde-manger =
    min(stock, besoin) si le plan a utilisé le stock, 0 sinon ; nouveau stock
    = (stock − consommé) + (acheté + consommé − besoin). Le second terme est
    exactement le w_i du solveur quand la récupération était active — c'est ce
    report qui rend σ_i honnête : la valeur résiduelle promise est réalisée.
    """
    if plan.status != PlanStatus.proposed:
        raise PlanNotCommittable(f"Plan {plan.id} déjà '{plan.status.value}'.")
    if plan.solver_status != "Optimal":
        raise PlanNotCommittable(
            f"Plan {plan.id} non commis : statut solveur '{plan.solver_status}'."
        )

    products = {
        p.id: p
        for p in session.scalars(
            select(Product).where(
                Product.id.in_({l["product_id"] for l in plan.purchases})
            )
        )
    }
    purchased: dict[str, Decimal] = {}
    for line in plan.purchases:
        prod = products[line["product_id"]]
        purchased[prod.canonical_ingredient_id] = (
            purchased.get(prod.canonical_ingredient_id, Decimal(0))
            + prod.package_qty_in_base_unit * line["units"]
        )

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
