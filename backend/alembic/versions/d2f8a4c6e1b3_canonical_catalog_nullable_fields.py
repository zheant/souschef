"""Allow uncurated canonical catalog values to remain unknown.

Revision ID: d2f8a4c6e1b3
Revises: b7e1d4a9c2f6
Create Date: 2026-08-12 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "d2f8a4c6e1b3"
down_revision = "b7e1d4a9c2f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_canonical_ingredient_perishability_01"),
        "canonical_ingredient", schema="catalog", type_="check",
    )
    op.drop_constraint(
        op.f("ck_canonical_ingredient_salvage_nonneg"),
        "canonical_ingredient", schema="catalog", type_="check",
    )
    op.alter_column(
        "canonical_ingredient", "perishability", schema="catalog",
        existing_type=sa.Numeric(4, 3), nullable=True,
    )
    op.alter_column(
        "canonical_ingredient", "salvage_value_cents_per_base_unit",
        schema="catalog", existing_type=sa.Numeric(14, 6), nullable=True,
    )
    op.create_check_constraint(
        op.f("ck_canonical_ingredient_perishability_01"),
        "canonical_ingredient",
        "perishability IS NULL OR (perishability >= 0 AND perishability <= 1)",
        schema="catalog",
    )
    op.create_check_constraint(
        op.f("ck_canonical_ingredient_salvage_nonneg"),
        "canonical_ingredient",
        "salvage_value_cents_per_base_unit IS NULL OR "
        "salvage_value_cents_per_base_unit >= 0",
        schema="catalog",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE catalog.canonical_ingredient SET perishability = 0 "
        "WHERE perishability IS NULL"
    )
    op.execute(
        "UPDATE catalog.canonical_ingredient "
        "SET salvage_value_cents_per_base_unit = 0 "
        "WHERE salvage_value_cents_per_base_unit IS NULL"
    )
    op.drop_constraint(
        op.f("ck_canonical_ingredient_perishability_01"),
        "canonical_ingredient", schema="catalog", type_="check",
    )
    op.drop_constraint(
        op.f("ck_canonical_ingredient_salvage_nonneg"),
        "canonical_ingredient", schema="catalog", type_="check",
    )
    op.alter_column(
        "canonical_ingredient", "perishability", schema="catalog",
        existing_type=sa.Numeric(4, 3), nullable=False,
    )
    op.alter_column(
        "canonical_ingredient", "salvage_value_cents_per_base_unit",
        schema="catalog", existing_type=sa.Numeric(14, 6), nullable=False,
    )
    op.create_check_constraint(
        op.f("ck_canonical_ingredient_perishability_01"),
        "canonical_ingredient",
        "perishability >= 0 AND perishability <= 1",
        schema="catalog",
    )
    op.create_check_constraint(
        op.f("ck_canonical_ingredient_salvage_nonneg"),
        "canonical_ingredient",
        "salvage_value_cents_per_base_unit >= 0",
        schema="catalog",
    )
