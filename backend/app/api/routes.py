"""Routes de l'API v1 — la couche expose des résultats calculés par les
services ; aucune logique métier ici, aucun accès aux ports d'ingestion."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import (
    CanonicalIngredient, HouseholdMember, HouseholdProfile, MappingStatus,
    PantryStock, Plan, ProductMapping, RawOffer, Recipe, Store,
)
from ..services.demand import compute_demand_bounds
from ..services.plan_service import (
    PlanNotCommittable, commit_plan, create_plan, grocery_list,
)
from ..solver import MenuSolver, SolverConfig
from . import schemas
from .deps import get_profile_id, get_session, get_solver

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Ménage
# ---------------------------------------------------------------------------

def _load_profile(session: Session, profile_id: str) -> HouseholdProfile:
    profile = session.get(HouseholdProfile, profile_id)
    if profile is None:
        raise HTTPException(404, f"Profil '{profile_id}' introuvable.")
    return profile


def _household_out(profile: HouseholdProfile) -> schemas.HouseholdOut:
    bounds = compute_demand_bounds(
        profile.meals_per_horizon,
        [m.appetite_coefficient for m in profile.members],
        profile.demand_slack_epsilon,
    )
    return schemas.HouseholdOut(
        id=profile.id, home_lat=float(profile.home_lat),
        home_lng=float(profile.home_lng),
        time_value_cents_per_hour=profile.time_value_cents_per_hour,
        meals_per_horizon=profile.meals_per_horizon,
        demand_slack_epsilon=float(profile.demand_slack_epsilon),
        max_store_visits=profile.max_store_visits,
        min_distinct_recipes=profile.min_distinct_recipes,
        max_share_per_recipe=float(profile.max_share_per_recipe),
        diet_flags=profile.diet_flags, allergen_flags=profile.allergen_flags,
        taste_preferences=profile.taste_preferences,
        available_equipment=profile.available_equipment,
        max_prep_time_per_meal_h=float(profile.max_prep_time_per_meal_h),
        members=[
            schemas.MemberOut(
                name=m.name, appetite_coefficient=float(m.appetite_coefficient)
            )
            for m in profile.members
        ],
        demand={
            "D_exact": str(bounds.exact),
            "borne_basse": bounds.low,
            "borne_haute": bounds.high,
        },
    )


@router.get("/household", response_model=schemas.HouseholdOut)
def get_household(
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
):
    return _household_out(_load_profile(session, profile_id))


@router.put("/household", response_model=schemas.HouseholdOut)
def put_household(
    body: schemas.HouseholdUpdate,
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
):
    profile = _load_profile(session, profile_id)
    data = body.model_dump(exclude_unset=True)
    members = data.pop("members", None)
    for field, value in data.items():
        setattr(profile, field, value)
    if members is not None:
        profile.members.clear()
        session.flush()
        for m in members:
            profile.members.append(
                HouseholdMember(
                    name=m["name"],
                    appetite_coefficient=Decimal(str(m["appetite_coefficient"])),
                )
            )
    session.flush()
    return _household_out(profile)


# ---------------------------------------------------------------------------
# Garde-manger
# ---------------------------------------------------------------------------

@router.get("/pantry")
def get_pantry(
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
):
    rows = session.scalars(
        select(PantryStock).where(PantryStock.household_profile_id == profile_id)
    ).all()
    return [
        {"canonical_ingredient_id": r.canonical_ingredient_id,
         "quantity_base_unit": str(r.quantity_base_unit)}
        for r in rows
    ]


@router.put("/pantry")
def put_pantry(
    body: schemas.PantryUpdate,
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
):
    known = set(session.scalars(select(CanonicalIngredient.id)).all())
    for line in body.lines:
        if line.canonical_ingredient_id not in known:
            raise HTTPException(
                422, f"Ingrédient inconnu : '{line.canonical_ingredient_id}'."
            )
        stmt = (
            pg_insert(PantryStock)
            .values(
                household_profile_id=profile_id,
                canonical_ingredient_id=line.canonical_ingredient_id,
                quantity_base_unit=Decimal(str(line.quantity_base_unit)),
            )
            .on_conflict_do_update(
                index_elements=["household_profile_id", "canonical_ingredient_id"],
                set_={"quantity_base_unit": Decimal(str(line.quantity_base_unit))},
            )
        )
        session.execute(stmt)
    return get_pantry(session=session, profile_id=profile_id)


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def _plan_out(session: Session, plan: Plan) -> schemas.PlanOut:
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
            schemas.MenuLine(
                recipe_id=rid, name=r.name, servings=x,
                prep_time_h=str(prep),
                attributed_cost_cents_cad=str(attributed),
            )
        )
    return schemas.PlanOut(
        id=plan.id, status=plan.status.value, solver_status=plan.solver_status,
        on_date=plan.on_date, menu=menu,
        grocery_list_by_store=grocery_list(session, plan),
        stores_visited=plan.stores_visited, diagnostic=plan.diagnostic,
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
    plan, result = create_plan(
        session, profile_id, body.on_date or date.today(), config, solver
    )
    if result.status != "Optimal":
        # Le plan (avec son diagnostic d'infaisabilité) est persisté et
        # retourné : l'écran Génération affiche le message du diagnostic.
        return _plan_out(session, plan)
    return _plan_out(session, plan)


@router.get("/plan/{plan_id}", response_model=schemas.PlanOut)
def get_plan(
    plan_id: int,
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
):
    plan = session.get(Plan, plan_id)
    if plan is None or plan.household_profile_id != profile_id:
        raise HTTPException(404, f"Plan {plan_id} introuvable.")
    return _plan_out(session, plan)


@router.post("/plan/{plan_id}/commit")
def post_commit(
    plan_id: int,
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
):
    plan = session.get(Plan, plan_id)
    if plan is None or plan.household_profile_id != profile_id:
        raise HTTPException(404, f"Plan {plan_id} introuvable.")
    try:
        new_stock = commit_plan(session, plan)
    except PlanNotCommittable as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"plan_id": plan.id, "status": plan.status.value,
            "pantry_after_commit": new_stock}


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
    stmt = select(Recipe).order_by(Recipe.id)
    if q:
        stmt = stmt.where(Recipe.name.ilike(f"%{q}%"))
    if diet:
        stmt = stmt.where(Recipe.diet_flags.contains([diet]))
    if tag_cuisine:
        stmt = stmt.where(Recipe.tags["cuisine"].astext == tag_cuisine)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.scalars(stmt.limit(limit).offset(offset)).all()
    return {
        "total": total, "limit": limit, "offset": offset,
        "items": [
            {
                "id": r.id, "name": r.name,
                "original_servings": r.original_servings,
                "prep_time_fixed_h": str(r.prep_time_fixed_h),
                "prep_time_marginal_h": str(r.prep_time_marginal_h),
                "min_batch_servings": r.min_batch_servings,
                "max_batch_servings": r.max_batch_servings,
                "tags": r.tags, "diet_flags": r.diet_flags,
                "allergen_flags": r.allergen_flags,
            }
            for r in rows
        ],
    }


@router.get("/stores")
def get_stores(session: Session = Depends(get_session)):
    return [
        {
            "external_key": s.external_key, "banner": s.banner,
            "address": s.address, "lat": float(s.lat), "lng": float(s.lng),
            "shopping_center_id": s.shopping_center_id,
        }
        for s in session.scalars(select(Store).order_by(Store.external_key))
    ]


@router.get("/ingredients/unmapped")
def get_unmapped(session: Session = Depends(get_session)):
    """File d'attente de mapping : offres en staging sans correspondance."""
    rows = session.execute(
        select(
            RawOffer.payload["raw_text"].astext.label("raw_text"),
            func.count().label("occurrences"),
        )
        .where(RawOffer.mapping_status == MappingStatus.unmapped)
        .group_by(RawOffer.payload["raw_text"].astext)
        .order_by(func.count().desc())
    ).all()
    return [{"raw_text": r.raw_text, "occurrences": r.occurrences} for r in rows]


@router.post("/ingredients/map")
def post_map(
    body: schemas.MapRequest,
    session: Session = Depends(get_session),
):
    if session.get(CanonicalIngredient, body.canonical_ingredient_id) is None:
        raise HTTPException(
            422, f"Ingrédient inconnu : '{body.canonical_ingredient_id}'."
        )
    stmt = (
        pg_insert(ProductMapping)
        .values(
            raw_text=body.raw_text,
            canonical_ingredient_id=body.canonical_ingredient_id,
            confidence=Decimal("1.000"),
            confirmed_by=body.confirmed_by,
        )
        .on_conflict_do_update(
            index_elements=["raw_text"],
            set_={
                "canonical_ingredient_id": body.canonical_ingredient_id,
                "confidence": Decimal("1.000"),
                "confirmed_by": body.confirmed_by,
            },
        )
    )
    session.execute(stmt)
    updated = 0
    for raw in session.scalars(
        select(RawOffer).where(
            RawOffer.mapping_status == MappingStatus.unmapped,
            RawOffer.payload["raw_text"].astext == body.raw_text,
        )
    ):
        raw.mapping_status = MappingStatus.confirmed
        updated += 1
    return {"raw_text": body.raw_text, "offers_confirmed": updated}
