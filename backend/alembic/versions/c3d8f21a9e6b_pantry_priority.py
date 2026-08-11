"""pantry stock priority (use_soon / must_use)

Revision ID: c3d8f21a9e6b
Revises: 9a2f6e1c4b7d
Create Date: 2026-08-11 12:00:00.000000

Pilote (docs/product-pilot.md), tranche « périssables prioritaires ou
obligatoires » : ``household.pantry_stock`` gagne ``priority`` (enum
``normal`` | ``use_soon`` | ``must_use``, NOT NULL, défaut ``normal`` —
comportement inchangé pour toute ligne existante). ``use_soon`` est stocké
sans effet sur le solveur en v1 (préférence, pas de sixième terme
d'objectif dans cette tranche) ; ``must_use`` alimente
``SolverConfig.must_use_pantry_ids`` (contrainte réelle,
``solver/model.py::_add_must_use_pantry``).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c3d8f21a9e6b'
down_revision = '9a2f6e1c4b7d'
branch_labels = None
depends_on = None

_ENUM_VALUES = ('normal', 'use_soon', 'must_use')


def _enum_type() -> postgresql.ENUM:
    return postgresql.ENUM(
        *_ENUM_VALUES, name='pantry_priority', schema='household'
    )


def upgrade() -> None:
    # op.add_column avec un sa.Enum ne crée PAS le type Postgres
    # automatiquement (contrairement à create_table) — vérifié en direct :
    # échoue avec UndefinedObject sans cette création explicite.
    _enum_type().create(op.get_bind(), checkfirst=True)
    op.add_column(
        'pantry_stock',
        sa.Column(
            'priority', _enum_type(), nullable=False, server_default='normal',
        ),
        schema='household',
    )
    op.alter_column(
        'pantry_stock', 'priority', server_default=None, schema='household'
    )


def downgrade() -> None:
    op.drop_column('pantry_stock', 'priority', schema='household')
    _enum_type().drop(op.get_bind(), checkfirst=True)
