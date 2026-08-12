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

Le ``commit`` (pilote, docs/product-pilot.md — depuis le retrait du
garde-manger) est une simple validation + passage à
``PlanStatus.committed`` : plus de stock à décrémenter/reporter, la
comptabilité qui rendait le terme de récupération honnête vivait dans
``pantry_stock``, retiré. ``finalize_plan`` (écran de confirmation
post-génération) est le nouveau point qui ajuste le plan une dernière fois
avant commit — il réutilise ``reoptimize_plan`` telle quelle, menu
verrouillé en entier. Les recettes des derniers plans commis alimentent la
pénalité de répétition du scoring d'appétence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CanonicalIngredient, Plan, PlanStatus, Product, Recipe, Staple
from ..models.base import utcnow
from ..services.appetence import RuleBasedAppetenceScorer
from ..services.prefilter import prefilter_recipes
from ..services.needs import ingredient_needs
from ..services.problem_data import load_problem_data
from ..services.validation import min_taxed_price_per_base_unit
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


class ConflictingRecipeSelectionError(ValueError):
    """Une recette à la fois verrouillée et exclue (l'API traduit en 422)."""


class PlanAlreadyCommittedError(ValueError):
    """Un plan déjà commis ne peut plus être réoptimisé (verrouiller/
    remplacer une recette, ou finaliser) — les achats ont déjà été ajustés
    pour le menu tel qu'accepté ; le modifier après coup désynchroniserait
    le menu réellement suivi (l'API traduit en 409)."""


@dataclass(frozen=True)
class MenuLine:
    recipe_id: str
    name: str
    servings: int
    prep_time_h: str
    attributed_cost_cents_cad: str


@dataclass(frozen=True)
class NeededIngredientLine:
    """Ingrédient requis par le menu du plan, pour l'écran de confirmation
    post-génération (pilote, docs/product-pilot.md) — tous les ingrédients
    sont montrés, pas seulement les essentiels ; ``is_staple`` permet au
    front de pré-décocher ceux que le ménage est supposé déjà avoir."""

    canonical_ingredient_id: str
    name: str
    is_staple: bool


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
    needed_ingredients: list[NeededIngredientLine]
    stores_visited: list[str]
    diagnostic: dict


@dataclass(frozen=True)
class CommitResult:
    plan_id: int
    status: str


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
    # nouvelle allergie déclarée entre deux générations, ou un ingrédient
    # devenu invendable) n'est pas repêchée par force_keep_ids
    # (services/prefilter.py) — c'est ici qu'on le détecte.
    surviving_ids = {r.id for r in pre.surviving}
    if not locked_recipe_ids <= surviving_ids:
        raise RecipeNotLockableError(
            "Recette(s) verrouillée(s) ne passant plus les filtres du "
            "profil actuel (allergènes/régime/équipement/temps/prix) : "
            f"{sorted(locked_recipe_ids - surviving_ids)}."
        )

    locked_recipe_servings = {
        rid: previous.servings[rid] for rid in locked_recipe_ids
    }
    reopt_config = config.model_copy(
        update={"locked_recipe_servings": locked_recipe_servings}
    )
    result = solver.solve(problem, pre, reopt_config)
    plan = _persist_plan(
        session, profile_id, previous.on_date, reopt_config, problem, result
    )

    view = _plan_view(session, plan)
    changes = None
    # Garde sur le plan PRÉCÉDENT aussi, pas seulement le nouveau : un plan
    # infaisable est persisté (routes.py le permet explicitement) et n'a pas
    # d'objective_terms_cents (None, voir _diagnostic_json) — sans cette
    # garde, réoptimiser/finaliser un plan infaisable qui réussit cette fois
    # lève TypeError sur `None["achats"]` et annule silencieusement le
    # commit du nouveau plan pourtant résolu (get_session ne commit qu'au
    # retour propre).
    if result.status == "Optimal" and previous.diagnostic.get("objective_terms_cents"):
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


def finalize_plan(
    session: Session,
    profile_id: str,
    plan_id: int,
    confirmed_available_ids: tuple[str, ...],
    config: SolverConfig,
    solver: MenuSolver,
) -> ReoptimizationResult:
    """Confirmation post-génération (pilote, docs/product-pilot.md) : dernier
    ajustement avant commit, une fois que l'usager a corrigé la liste des
    ingrédients qu'il possède déjà réellement. Verrouille systématiquement
    tout le menu courant — jamais un choix de l'appelant, contrairement à
    Replanifier : finaliser ne doit jamais changer les recettes, seulement
    la logistique d'achat. Aucune résolution séparée : un appel de plus au
    même mécanisme déjà éprouvé (``reoptimize_plan``)."""
    previous = _load_owned_plan(session, profile_id, plan_id)
    all_recipe_ids = frozenset(previous.servings.keys())
    finalize_config = config.model_copy(
        update={
            "enable_staples": False,
            "confirmed_available_ids": tuple(confirmed_available_ids),
        }
    )
    return reoptimize_plan(
        session, profile_id, plan_id,
        all_recipe_ids, frozenset(),
        finalize_config, solver,
    )


def get_plan(session: Session, profile_id: str, plan_id: int) -> PlanView:
    return _plan_view(session, _load_owned_plan(session, profile_id, plan_id))


def commit_plan(session: Session, profile_id: str, plan_id: int) -> CommitResult:
    plan = _load_owned_plan(session, profile_id, plan_id)
    if plan.status != PlanStatus.proposed:
        raise PlanNotCommittable(f"Plan {plan.id} déjà '{plan.status.value}'.")
    if plan.solver_status != "Optimal":
        raise PlanNotCommittable(
            f"Plan {plan.id} non commis : statut solveur '{plan.solver_status}'."
        )
    plan.status = PlanStatus.committed
    plan.committed_at = utcnow()
    session.flush()
    return CommitResult(plan_id=plan.id, status=plan.status.value)


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
    # Une recette dont un ingrédient n'a plus aucun produit prixé est exclue
    # ici, avant le solveur — même ensemble que l'assertion 4
    # (min_taxed_price_per_base_unit) : évite qu'un ingrédient invendable
    # atteigne validate_problem sans distinguer s'il est confirmé disponible
    # ou non (les deux tombaient sinon sur la même MissingPriceError non
    # gérée par l'API).
    priced_ids = frozenset(min_taxed_price_per_base_unit(problem))
    return prefilter_recipes(
        problem.recipes, problem.profile, scorer, priced_ids,
        force_keep_ids=force_keep_ids, exclude_ids=exclude_ids,
    )


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
                "gaspillage": str(t.gaspillage_cents),
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
        needed_ingredients=_needed_ingredients(session, plan),
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


def _needed_ingredients(session: Session, plan: Plan) -> list[NeededIngredientLine]:
    """Tous les ingrédients requis par le menu du plan (pilote,
    docs/product-pilot.md) — écran de confirmation post-génération : montre
    tout, pas seulement les essentiels, pré-décochés côté front via
    ``is_staple`` pour que l'usager corrige ce qui manque réellement."""
    ids = sorted(plan.ingredient_needs.keys())
    if not ids:
        return []
    names = {
        i.id: i.name
        for i in session.scalars(
            select(CanonicalIngredient).where(CanonicalIngredient.id.in_(ids))
        )
    }
    staples = set(session.scalars(
        select(Staple.canonical_ingredient_id).where(
            Staple.household_profile_id == plan.household_profile_id,
            Staple.canonical_ingredient_id.in_(ids),
        )
    ).all())
    return [
        NeededIngredientLine(
            canonical_ingredient_id=iid, name=names[iid], is_staple=iid in staples,
        )
        for iid in ids
    ]


