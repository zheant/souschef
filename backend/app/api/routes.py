"""Routes de l'API v1 — la couche expose des résultats calculés par les
modules applicatifs (``services/planning.py``, ``services/household.py``,
``services/catalog.py``, ``services/offer_resolution.py``) ; aucune logique
métier ici, aucun accès direct à SQLAlchemy/aux modèles ORM, aucun accès aux
ports d'ingestion."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..services import catalog, household, offer_resolution, planning
from ..solver import MenuSolver, SolverConfig
from . import schemas
from .deps import get_profile_id, get_session, get_solver

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Ménage
# ---------------------------------------------------------------------------

def _household_out(view: household.HouseholdView) -> schemas.HouseholdOut:
    return schemas.HouseholdOut(
        id=view.id, home_lat=view.home_lat, home_lng=view.home_lng,
        time_value_cents_per_hour=view.time_value_cents_per_hour,
        meals_per_horizon=view.meals_per_horizon,
        demand_slack_epsilon=view.demand_slack_epsilon,
        max_store_visits=view.max_store_visits,
        min_distinct_recipes=view.min_distinct_recipes,
        max_share_per_recipe=view.max_share_per_recipe,
        diet_flags=view.diet_flags, allergen_flags=view.allergen_flags,
        taste_preferences=view.taste_preferences,
        available_equipment=view.available_equipment,
        max_prep_time_per_meal_h=view.max_prep_time_per_meal_h,
        members=[schemas.MemberOut(**asdict(m)) for m in view.members],
        demand=view.demand,
    )


@router.get("/household", response_model=schemas.HouseholdOut)
def get_household(
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
):
    try:
        return _household_out(household.get_profile(session, profile_id))
    except household.ProfileNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/household", response_model=schemas.HouseholdOut)
def put_household(
    body: schemas.HouseholdUpdate,
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
):
    try:
        view = household.update_profile(
            session, profile_id, body.model_dump(exclude_unset=True)
        )
    except household.ProfileNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return _household_out(view)


# ---------------------------------------------------------------------------
# Garde-manger
# ---------------------------------------------------------------------------

@router.get("/pantry")
def get_pantry(
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
):
    return [asdict(line) for line in household.get_pantry(session, profile_id)]


@router.put("/pantry")
def put_pantry(
    body: schemas.PantryUpdate,
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
):
    try:
        lines = household.update_pantry(
            session, profile_id, [line.model_dump() for line in body.lines]
        )
    except household.UnknownIngredientError as exc:
        raise HTTPException(422, str(exc)) from exc
    return [asdict(line) for line in lines]


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def _plan_out(view: planning.PlanView) -> schemas.PlanOut:
    return schemas.PlanOut(
        id=view.id, status=view.status, solver_status=view.solver_status,
        on_date=view.on_date,
        menu=[schemas.MenuLine(**asdict(m)) for m in view.menu],
        grocery_list_by_store=view.grocery_list_by_store,
        stores_visited=view.stores_visited, diagnostic=view.diagnostic,
    )


@router.post("/plan", response_model=schemas.PlanOut)
def post_plan(
    body: schemas.PlanRequest,
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
    solver: MenuSolver = Depends(get_solver),
):
    try:
        config = SolverConfig(**body.config)
    except ValueError as exc:
        raise HTTPException(422, f"SolverConfig invalide : {exc}") from exc
    # Un plan infaisable (statut solveur != Optimal) est aussi persisté et
    # retourné : l'écran Génération affiche le message du diagnostic.
    view = planning.generate_plan(
        session, profile_id, body.on_date or date.today(), config, solver
    )
    return _plan_out(view)


@router.get("/plan/{plan_id}", response_model=schemas.PlanOut)
def get_plan(
    plan_id: int,
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
):
    try:
        return _plan_out(planning.get_plan(session, profile_id, plan_id))
    except planning.PlanNotFound as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get(
    "/plan/{plan_id}/pantry_prompt", response_model=list[schemas.PantryPromptLineOut]
)
def get_pantry_prompt(
    plan_id: int,
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
):
    try:
        lines = planning.pantry_prompt(session, profile_id, plan_id)
    except planning.PlanNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return [schemas.PantryPromptLineOut(**asdict(line)) for line in lines]


@router.post("/plan/{plan_id}/commit")
def post_commit(
    plan_id: int,
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
):
    try:
        result = planning.commit_plan(session, profile_id, plan_id)
    except planning.PlanNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except planning.PlanNotCommittable as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"plan_id": result.plan_id, "status": result.status,
            "pantry_after_commit": result.pantry_after_commit}


@router.post("/plan/{plan_id}/reoptimize", response_model=schemas.ReoptimizeOut)
def post_reoptimize(
    plan_id: int,
    body: schemas.ReoptimizeRequest,
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
    solver: MenuSolver = Depends(get_solver),
):
    try:
        config = SolverConfig(**body.config)
    except ValueError as exc:
        raise HTTPException(422, f"SolverConfig invalide : {exc}") from exc
    try:
        result = planning.reoptimize_plan(
            session, profile_id, plan_id,
            frozenset(body.locked_recipe_ids),
            frozenset(body.excluded_recipe_ids),
            config, solver,
        )
    except planning.PlanNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except planning.RecipeNotInPlanError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (
        planning.RecipeNotLockableError, planning.ConflictingRecipeSelectionError,
    ) as exc:
        raise HTTPException(422, str(exc)) from exc
    return schemas.ReoptimizeOut(
        plan=_plan_out(result.plan),
        changes=(
            schemas.MenuChangeOut(**asdict(result.changes))
            if result.changes else None
        ),
    )


# ---------------------------------------------------------------------------
# Catalogue et marché
# ---------------------------------------------------------------------------

@router.get("/recipes")
def get_recipes(
    session: Session = Depends(get_session),
    q: str | None = Query(default=None, description="recherche par nom"),
    diet: str | None = Query(default=None),
    tag_cuisine: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    page = catalog.search_recipes(
        session,
        catalog.RecipeQuery(
            q=q, diet=diet, tag_cuisine=tag_cuisine, limit=limit, offset=offset
        ),
    )
    return {
        "total": page.total, "limit": page.limit, "offset": page.offset,
        "items": [asdict(item) for item in page.items],
    }


@router.get("/stores")
def get_stores(session: Session = Depends(get_session)):
    return [asdict(s) for s in catalog.list_stores(session)]


# ---------------------------------------------------------------------------
# Mapping produit (D15/D18, docs/deviations.md)
# ---------------------------------------------------------------------------

@router.get("/ingredients/unmapped")
def get_unmapped(session: Session = Depends(get_session)):
    """File d'attente de résolution : offres en staging sans correspondance."""
    return [asdict(o) for o in offer_resolution.list_unresolved(session)]


@router.post("/ingredients/map")
def post_map(
    body: schemas.MapRequest,
    session: Session = Depends(get_session),
):
    try:
        if body.product_id is not None:
            result = offer_resolution.attach_existing_product(
                session, body.store_external_key, body.raw_text,
                body.product_id, body.confirmed_by,
            )
        else:
            spec = offer_resolution.NewProductSpec(**body.new_product.model_dump())
            result = offer_resolution.create_and_attach_product(
                session, body.store_external_key, body.raw_text, spec,
                body.confirmed_by,
            )
    except (
        offer_resolution.UnknownStoreError, offer_resolution.UnknownProductError,
    ) as exc:
        raise HTTPException(404, str(exc)) from exc
    except offer_resolution.UnknownCanonicalIngredientError as exc:
        raise HTTPException(422, str(exc)) from exc
    return asdict(result)
