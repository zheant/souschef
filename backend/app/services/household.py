"""``HouseholdModule`` — profil du ménage et essentiels (staples).

Même convention que ``services/planning.py`` : chaque fonction garde
``session: Session`` en premier paramètre explicite, pas de session ouverte
en interne (voir la docstring de ``planning.py`` pour la raison — préserver
l'override de test FastAPI).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import CanonicalIngredient, HouseholdMember, HouseholdProfile, Staple
from ..services.demand import compute_demand_bounds


class ProfileNotFound(LookupError):
    """Aucun profil de ménage avec cet id (l'API traduit en 404)."""


class UnknownIngredientError(ValueError):
    """Essentiel référençant un ingrédient canonique inconnu (l'API traduit
    en 422)."""


@dataclass(frozen=True)
class MemberView:
    name: str
    appetite_coefficient: float


@dataclass(frozen=True)
class HouseholdView:
    id: str
    home_lat: float
    home_lng: float
    time_value_cents_per_hour: int
    meals_per_horizon: int
    demand_slack_epsilon: float
    max_store_visits: int
    min_distinct_recipes: int
    max_share_per_recipe: float
    diet_flags: list
    allergen_flags: list
    taste_preferences: dict
    available_equipment: list
    max_prep_time_per_meal_h: float
    #: U_min — plancher d'appétence du plan, en dollars. `None` : aucun
    #: plancher, l'appétence reste un crédit dans l'objectif.
    appetence_u_min_dollars: float | None
    min_protein_g_per_serving: float | None
    max_distinct_recipes: int | None
    #: Plancher de dépense d'épicerie, en cents CAD. `None` : aucun plancher.
    members: list[MemberView]
    #: D exact + bornes (D9) — structure documentée dans docs/spec.md.
    demand: dict


@dataclass(frozen=True)
class StapleLine:
    canonical_ingredient_id: str
    name: str


def get_profile(session: Session, profile_id: str) -> HouseholdView:
    return _profile_view(_load_profile(session, profile_id))


def update_profile(
    session: Session, profile_id: str, changes: dict
) -> HouseholdView:
    profile = _load_profile(session, profile_id)
    data = dict(changes)
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
    return _profile_view(profile)


def get_staples(session: Session, profile_id: str) -> tuple[StapleLine, ...]:
    rows = session.execute(
        select(Staple.canonical_ingredient_id, CanonicalIngredient.name)
        .join(
            CanonicalIngredient,
            CanonicalIngredient.id == Staple.canonical_ingredient_id,
        )
        .where(Staple.household_profile_id == profile_id)
        .order_by(CanonicalIngredient.name)
    ).all()
    return tuple(
        StapleLine(canonical_ingredient_id=r[0], name=r[1]) for r in rows
    )


def set_staples(
    session: Session, profile_id: str, canonical_ingredient_ids: list[str]
) -> tuple[StapleLine, ...]:
    """Remplace l'ensemble complet des essentiels du ménage — pas un upsert
    ligne par ligne comme l'ancien garde-manger (qui devait préserver
    quantité/priorité par ligne) : un essentiel est une simple appartenance,
    sans quantité ni priorité, donc la liste est éditée comme un tout,
    cohérent avec la sauvegarde du profil."""
    known = set(session.scalars(select(CanonicalIngredient.id)).all())
    unknown = set(canonical_ingredient_ids) - known
    if unknown:
        raise UnknownIngredientError(
            f"Ingrédient(s) inconnu(s) : {', '.join(sorted(unknown))}."
        )
    session.execute(delete(Staple).where(Staple.household_profile_id == profile_id))
    session.flush()
    for iid in canonical_ingredient_ids:
        session.add(
            Staple(household_profile_id=profile_id, canonical_ingredient_id=iid)
        )
    session.flush()
    return get_staples(session, profile_id)


def _load_profile(session: Session, profile_id: str) -> HouseholdProfile:
    profile = session.get(HouseholdProfile, profile_id)
    if profile is None:
        raise ProfileNotFound(f"Profil '{profile_id}' introuvable.")
    return profile


def _profile_view(profile: HouseholdProfile) -> HouseholdView:
    bounds = compute_demand_bounds(
        profile.meals_per_horizon,
        [m.appetite_coefficient for m in profile.members],
        profile.demand_slack_epsilon,
    )
    return HouseholdView(
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
        max_distinct_recipes=profile.max_distinct_recipes,
        min_protein_g_per_serving=(
            float(profile.min_protein_g_per_serving)
            if profile.min_protein_g_per_serving is not None
            else None
        ),
        appetence_u_min_dollars=(
            float(profile.appetence_u_min_dollars)
            if profile.appetence_u_min_dollars is not None
            else None
        ),
        members=[
            MemberView(
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
