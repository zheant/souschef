"""Base déclarative commune.

Conventions transverses (docs/spec.md, « Exigences transverses ») :
- aucun montant d'argent en flottant : entiers en cents (``*_cents_cad``) ou
  ``Numeric`` lorsque la grandeur est sub-cent (ex. valeur de récupération par
  gramme) ;
- les unités apparaissent dans les noms de colonnes (``*_base_unit``, ``*_h``,
  ``*_cents_cad``, ``*_g_per_ml``) ;
- clés primaires « naturelles » (slugs texte stables) pour les entités seedées,
  afin que le seeding soit idempotent par simple upsert.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Convention de nommage stable → migrations Alembic déterministes.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
