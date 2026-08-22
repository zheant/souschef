"""Plancher de protéines du ménage : grammes par portion, moyenne du menu (D41).

Le pendant du plancher d'appétence (U_min), dans l'unité que le ménage
surveille. `NULL` veut dire « aucun plancher » — pas zéro : un plancher à zéro
serait une contrainte satisfaite d'avance, et le solveur la construirait pour
rien.

Revision ID: 8ec98af31b5e
Revises: 853a7ffc6022
"""
from alembic import op
import sqlalchemy as sa


revision = "8ec98af31b5e"
down_revision = "853a7ffc6022"
branch_labels = None
depends_on = None

SCHEMA = "household"
TABLE = "household_profile"
COLUMN = "min_protein_g_per_serving"
CONSTRAINT = "min_protein_nonneg"


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
    op.drop_constraint(CONSTRAINT, TABLE, type_="check", schema=SCHEMA)
    op.drop_column(TABLE, COLUMN, schema=SCHEMA)
