"""variable weight products and pricing confidence

Revision ID: e8a1c4d7f2b9
Revises: d2f8a4c6e1b3
Create Date: 2026-08-13 17:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e8a1c4d7f2b9"
down_revision = "d2f8a4c6e1b3"
branch_labels = None
depends_on = None

_SALE_MODES = ("fixed_package", "variable_weight")
_PRICING_CONFIDENCE = (
    "exact",
    "audited_conversion",
    "estimated",
    "incomplete",
)


def upgrade() -> None:
    sale_mode = postgresql.ENUM(
        *_SALE_MODES, name="sale_mode", schema="market", create_type=False
    )
    confidence = postgresql.ENUM(
        *_PRICING_CONFIDENCE,
        name="pricing_confidence",
        schema="market",
        create_type=False,
    )
    sale_mode.create(op.get_bind(), checkfirst=True)
    confidence.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "product",
        sa.Column(
            "sale_mode",
            sale_mode,
            server_default="fixed_package",
            nullable=False,
        ),
        schema="market",
    )
    op.add_column(
        "product",
        sa.Column(
            "purchase_increment_in_base_unit", sa.Numeric(12, 3), nullable=True
        ),
        schema="market",
    )
    op.add_column(
        "product",
        sa.Column(
            "quantity_confidence",
            confidence,
            server_default="exact",
            nullable=False,
        ),
        schema="market",
    )
    op.add_column(
        "product",
        sa.Column("quantity_provenance", sa.String(length=512), nullable=True),
        schema="market",
    )
    op.create_check_constraint(
        "purchase_increment_positive",
        "product",
        "purchase_increment_in_base_unit IS NULL OR "
        "purchase_increment_in_base_unit > 0",
        schema="market",
    )
    op.add_column(
        "price",
        sa.Column(
            "pricing_confidence",
            confidence,
            server_default="exact",
            nullable=False,
        ),
        schema="market",
    )
    op.alter_column("product", "sale_mode", server_default=None, schema="market")
    op.alter_column(
        "product", "quantity_confidence", server_default=None, schema="market"
    )
    op.alter_column(
        "price", "pricing_confidence", server_default=None, schema="market"
    )


def downgrade() -> None:
    op.drop_column("price", "pricing_confidence", schema="market")
    op.drop_column("product", "quantity_provenance", schema="market")
    op.drop_column("product", "quantity_confidence", schema="market")
    op.drop_constraint(
        "purchase_increment_positive", "product", schema="market", type_="check"
    )
    op.drop_column(
        "product", "purchase_increment_in_base_unit", schema="market"
    )
    op.drop_column("product", "sale_mode", schema="market")
    postgresql.ENUM(
        *_PRICING_CONFIDENCE,
        name="pricing_confidence",
        schema="market",
    ).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        *_SALE_MODES, name="sale_mode", schema="market"
    ).drop(op.get_bind(), checkfirst=True)
