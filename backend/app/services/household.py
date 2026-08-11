"""``HouseholdModule`` — profil du ménage et garde-manger.

Même convention que ``services/planning.py`` : chaque fonction garde
``session: Session`` en premier paramètre explicite, pas de session ouverte
en interne (voir la docstring de ``planning.py`` pour la raison — préserver
l'override de test FastAPI).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import CanonicalIngredient, HouseholdMember, HouseholdProfile, PantryStock
from ..services.demand import compute_demand_bounds


class ProfileNotFound(LookupError):
    """Aucun profil de ménage avec cet id (l'API traduit en 404)."""


class UnknownIngredientError(ValueError):
    """Ligne de garde-manger référençant un ingrédient canonique inconnu
    (l'API traduit en 422)."""


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
    members: list[MemberView]
    #: D exact + bornes (D9) — structure documentée dans docs/spec.md.
    demand: dict


@dataclass(frozen=True)
class PantryLine:
    canonical_ingredient_id: str
    quantity_base_unit: str


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


def get_pantry(session: Session, profile_id: str) -> tuple[PantryLine, ...]:
    rows = session.scalars(
        select(PantryStock).where(PantryStock.household_profile_id == profile_id)
    ).all()
    return tuple(
        PantryLine(
            canonical_ingredient_id=r.canonical_ingredient_id,
            quantity_base_unit=str(r.quantity_base_unit),
        )
        for r in rows
    )


def update_pantry(
    session: Session, profile_id: str, lines: list[dict]
) -> tuple[PantryLine, ...]:
    known = set(session.scalars(select(CanonicalIngredient.id)).all())
    for line in lines:
        if line["canonical_ingredient_id"] not in known:
            raise UnknownIngredientError(
                f"Ingrédient inconnu : '{line['canonical_ingredient_id']}'."
            )
        stmt = (
            pg_insert(PantryStock)
            .values(
                household_profile_id=profile_id,
                canonical_ingredient_id=line["canonical_ingredient_id"],
                quantity_base_unit=Decimal(str(line["quantity_base_unit"])),
            )
            .on_conflict_do_update(
                index_elements=["household_profile_id", "canonical_ingredient_id"],
                set_={"quantity_base_unit": Decimal(str(line["quantity_base_unit"]))},
            )
        )
        session.execute(stmt)
    return get_pantry(session, profile_id)


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
