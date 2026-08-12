"""staples replace pantry

Revision ID: f4b1a9d0c2e6
Revises: c3d8f21a9e6b
Create Date: 2026-08-12 09:00:00.000000

Retrait complet du garde-manger à quantité suivie (``pantry_stock`` +
l'enum ``pantry_priority``) — décision de l'utilisateur après deux
tranches successives (« à acheter », deux correctifs puis un remplacement
par Replanifier) qui ont montré la fragilité structurelle de reposer sur
un input utilisateur (quantités déclarées) qui diverge inévitablement du
stock réel. Remplacé par ``household.staple`` : une simple appartenance
ménage/ingrédient, sans quantité ni priorité — un essentiel est acheté
comme n'importe quel ingrédient, seulement évalué au prix historique le
plus bas dans l'objectif du solveur (voir
``services/pricing.py::historical_min_price_per_base_unit``).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'f4b1a9d0c2e6'
down_revision = 'c3d8f21a9e6b'
branch_labels = None
depends_on = None

_PRIORITY_VALUES = ('normal', 'use_soon', 'must_use')


def _priority_enum() -> postgresql.ENUM:
    return postgresql.ENUM(
        *_PRIORITY_VALUES, name='pantry_priority', schema='household'
    )


def upgrade() -> None:
    op.drop_table('pantry_stock', schema='household')
    _priority_enum().drop(op.get_bind(), checkfirst=True)
    op.create_table(
        'staple',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('household_profile_id', sa.String(length=64), nullable=False),
        sa.Column('canonical_ingredient_id', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['canonical_ingredient_id'], ['catalog.canonical_ingredient.id'],
            name=op.f('fk_staple_canonical_ingredient_id_canonical_ingredient'),
        ),
        sa.ForeignKeyConstraint(
            ['household_profile_id'], ['household.household_profile.id'],
            name=op.f('fk_staple_household_profile_id_household_profile'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_staple')),
        sa.UniqueConstraint(
            'household_profile_id', 'canonical_ingredient_id',
            name=op.f('uq_staple_household_profile_id_canonical_ingredient_id'),
        ),
        schema='household',
    )


def downgrade() -> None:
    op.drop_table('staple', schema='household')
    op.create_table(
        'pantry_stock',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('household_profile_id', sa.String(length=64), nullable=False),
        sa.Column('canonical_ingredient_id', sa.String(length=64), nullable=False),
        sa.Column('quantity_base_unit', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('quantity_base_unit >= 0', name=op.f('ck_pantry_stock_qty_nonneg')),
        sa.ForeignKeyConstraint(
            ['canonical_ingredient_id'], ['catalog.canonical_ingredient.id'],
            name=op.f('fk_pantry_stock_canonical_ingredient_id_canonical_ingredient'),
        ),
        sa.ForeignKeyConstraint(
            ['household_profile_id'], ['household.household_profile.id'],
            name=op.f('fk_pantry_stock_household_profile_id_household_profile'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_pantry_stock')),
        sa.UniqueConstraint(
            'household_profile_id', 'canonical_ingredient_id',
            name=op.f('uq_pantry_stock_household_profile_id_canonical_ingredient_id'),
        ),
        schema='household',
    )
    _priority_enum().create(op.get_bind(), checkfirst=True)
    op.add_column(
        'pantry_stock',
        sa.Column('priority', _priority_enum(), nullable=False, server_default='normal'),
        schema='household',
    )
    op.alter_column('pantry_stock', 'priority', server_default=None, schema='household')
