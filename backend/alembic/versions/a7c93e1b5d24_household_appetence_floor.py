"""Plancher d'appétence sur le profil de ménage.

`appetence_u_min_dollars` rejoint les paramètres surchargeables du profil
(K, R_min, α, ε) : la préférence persiste, au lieu de vivre dans l'état d'un
onglet développeur qui repart au défaut à chaque rafraîchissement.

`NULL` reproduit exactement le comportement d'avant cette migration — aucun
plancher, l'appétence reste un crédit dans l'objectif. Rien à remplir pour les
profils existants.

Revision ID: a7c93e1b5d24
Revises: e8a1c4d7f2b9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7c93e1b5d24"
down_revision = "e8a1c4d7f2b9"
branch_labels = None
depends_on = None

SCHEMA = "household"
TABLE = "household_profile"
COLUMN = "appetence_u_min_dollars"
CONSTRAINT = "u_min_nonneg"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(COLUMN, sa.Numeric(8, 2), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        CONSTRAINT,
        TABLE,
        f"{COLUMN} IS NULL OR {COLUMN} >= 0",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, schema=SCHEMA, type_="check")
    op.drop_column(TABLE, COLUMN, schema=SCHEMA)
