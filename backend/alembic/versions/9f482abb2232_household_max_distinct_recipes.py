"""R_max : nombre maximal de plats distincts au menu (D42).

Le pendant de R_min, mais il s'applique même sans le drapeau de diversité :
R_min sert à forcer la variété quand on l'étudie, R_max à borner ce qu'un ménage
accepte de cuisiner dans une semaine. `NULL` veut dire « aucun plafond » — et le
minimum est 1, pas 0 : un menu sans plat n'est pas un menu.

Revision ID: 9f482abb2232
Revises: 8ec98af31b5e
"""
from alembic import op
import sqlalchemy as sa


revision = "9f482abb2232"
down_revision = "8ec98af31b5e"
branch_labels = None
depends_on = None

SCHEMA = "household"
TABLE = "household_profile"
COLUMN = "max_distinct_recipes"
CONSTRAINT = "r_max_at_least_one"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(COLUMN, sa.Integer(), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        CONSTRAINT,
        TABLE,
        f"{COLUMN} IS NULL OR {COLUMN} >= 1",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="check", schema=SCHEMA)
    op.drop_column(TABLE, COLUMN, schema=SCHEMA)
