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

from ..services import catalog, household, offer_resolution, planning, recipe_quotes
from ..services.validation import ValidationError
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
        appetence_u_min_dollars=view.appetence_u_min_dollars,
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
# Essentiels (staples)
# ---------------------------------------------------------------------------

@router.get("/staples")
def get_staples(
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
):
    return [asdict(line) for line in household.get_staples(session, profile_id)]


@router.put("/staples")
def put_staples(
    body: schemas.StaplesUpdate,
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
):
    try:
        lines = household.set_staples(
            session, profile_id, body.canonical_ingredient_ids
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
        needed_ingredients=[
            schemas.NeededIngredientOut(**asdict(l)) for l in view.needed_ingredients
        ],
        stores_visited=view.stores_visited, diagnostic=view.diagnostic,
    )


def _config_error(exc: Exception) -> HTTPException:
    """422 lisible pour un `SolverConfig` refusé.

    `str()` sur une `ValidationError` de Pydantic recrache le dictionnaire
    d'entrée complet et une URL de documentation — affiché tel quel à l'écran,
    ça noyait la seule phrase utile (« appetence_mode='constraint' exige
    appetence_u_min_dollars »). On ne garde que les messages.
    """
    errors = getattr(exc, "errors", None)
    if callable(errors):
        messages = []
        for err in errors():
            msg = str(err.get("msg", "")).removeprefix("Value error, ").strip()
            loc = ".".join(str(x) for x in err.get("loc", ()))
            messages.append(f"{loc} : {msg}" if loc and loc not in msg else msg)
        if messages:
            return HTTPException(422, "SolverConfig invalide — " + " ; ".join(messages))
    return HTTPException(422, f"SolverConfig invalide : {exc}")


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
        raise _config_error(exc) from exc
    # Un plan infaisable (statut solveur != Optimal) est aussi persisté
    # et retourné : l'écran Génération affiche le message du diagnostic.
    #
    # Une assertion de validité qui échoue est une condition métier, pas une
    # panne : catalogue de prix périmé, profil sans demande, aucun magasin.
    # Non traduite, elle sortait en 500 « Internal Server Error » — l'écran
    # n'avait alors rien à montrer sinon un code, alors que le message porte
    # déjà la cause et le geste correctif.
    try:
        view = planning.generate_plan(
            session, profile_id, body.on_date or date.today(), config, solver
        )
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
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
    return {"plan_id": result.plan_id, "status": result.status}


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
        raise _config_error(exc) from exc
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
    except planning.PlanAlreadyCommittedError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (
        planning.RecipeNotLockableError, planning.ConflictingRecipeSelectionError,
    ) as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValidationError as exc:
        # Même raison que sur POST /plan : condition métier, pas panne.
        raise HTTPException(422, str(exc)) from exc
    return schemas.ReoptimizeOut(
        plan=_plan_out(result.plan),
        changes=(
            schemas.MenuChangeOut(**asdict(result.changes))
            if result.changes else None
        ),
    )


@router.post("/plan/{plan_id}/finalize", response_model=schemas.ReoptimizeOut)
def post_finalize(
    plan_id: int,
    body: schemas.FinalizeRequest,
    session: Session = Depends(get_session),
    profile_id: str = Depends(get_profile_id),
    solver: MenuSolver = Depends(get_solver),
):
    """Confirmation post-génération (pilote, docs/product-pilot.md) — le
    menu reste verrouillé en entier, seule la logistique d'achat peut
    changer selon les ingrédients confirmés déjà possédés."""
    try:
        config = SolverConfig(**body.config)
    except ValueError as exc:
        raise _config_error(exc) from exc
    try:
        result = planning.finalize_plan(
            session, profile_id, plan_id,
            tuple(body.confirmed_available_ids),
            config, solver,
        )
    except planning.PlanNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except planning.PlanAlreadyCommittedError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValidationError as exc:
        # Même raison que sur POST /plan : condition métier, pas panne.
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
    """Recherche/pagination de recettes (docs/spec.md). Sans appelant
    frontend à ce jour — aucune tranche pilote n'a eu besoin d'un
    navigateur de recettes ; conservé tel quel, pas du code mort (implémente
    un endpoint requis par la spec), juste hors périmètre du pilote."""
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


@router.get("/recipe-quotes")
def get_recipe_quotes(
    on_date: date = Query(default_factory=date.today),
    recipe_id: str | None = Query(default=None),
    servings: int | None = Query(default=None, ge=1),
    store: list[str] | None = Query(default=None),
    session: Session = Depends(get_session),
):
    """Prix consommé et décaissement, avec preuve et niveau de confiance."""
    try:
        quotes = recipe_quotes.quote_recipes(
            session,
            on_date,
            recipe_id=recipe_id,
            servings=servings,
            store_external_keys=tuple(store or ()),
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except recipe_quotes.RecipeNotScalableError as exc:
        # L'appelant demande un rendement que la recette ne sait pas produire :
        # le lui dire plutôt que de renvoyer le même panier sous un prix par
        # portion faux.
        raise HTTPException(422, str(exc)) from exc
    except recipe_quotes.ProcurementRulesUnavailable as exc:
        # Un défaut de déploiement, pas une faute de l'appelant : le dire
        # explicitement plutôt que de laisser filer une trace de pile.
        raise HTTPException(503, str(exc)) from exc
    return [quote.as_dict() for quote in quotes]


@router.get(
    "/recipes/{recipe_id}/ingredients",
    response_model=list[schemas.RecipeIngredientOut],
)
def get_recipe_ingredients(
    recipe_id: str, session: Session = Depends(get_session)
):
    try:
        lines = catalog.get_recipe_ingredients(session, recipe_id)
    except catalog.RecipeNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return [schemas.RecipeIngredientOut(**asdict(line)) for line in lines]


@router.get("/stores")
def get_stores(session: Session = Depends(get_session)):
    return [asdict(s) for s in catalog.list_stores(session)]


@router.get("/price-coverage", response_model=schemas.PriceCoverageOut)
def get_price_coverage(session: Session = Depends(get_session)):
    """Fenêtre de dates que les prix chargés couvrent réellement.

    Demander un plan hors de cette fenêtre échoue légitimement (aucun prix
    valide, donc aucune recette après préfiltrage). L'écran de génération la
    lit pour proposer une date atteignable plutôt que de laisser l'usager
    découvrir la borne par un échec.
    """
    coverage = catalog.price_coverage(session)
    return schemas.PriceCoverageOut(
        earliest=coverage.earliest, latest=coverage.latest
    )


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
