"""Retirer le plancher de dépense d'épicerie du profil de ménage (D40).

Le paramètre est retiré du produit : la colonne part avec lui plutôt que de
rester en base sans personne pour la lire. Le `downgrade` la restaure avec sa
contrainte, à l'identique de la migration qui l'avait créée
(`b3f7c1a8d954`) — mais **pas les valeurs** : une colonne supprimée emporte ce
qu'elle contenait. Sur cette base, une seule ligne de profil existe et son
plancher valait 60 $ ; la valeur est rappelée ici pour qu'un retour arrière
puisse la ressaisir, et non retrouvée par magie.

Revision ID: 853a7ffc6022
Revises: a3e7c1f9b204
"""
from alembic import op
import sqlalchemy as sa


revision = "853a7ffc6022"
down_revision = "a3e7c1f9b204"
branch_labels = None
depends_on = None

SCHEMA = "household"
TABLE = "household_profile"
COLUMN = "min_grocery_spend_cents_cad"
CONSTRAINT = "min_spend_nonneg"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="check", schema=SCHEMA)
    op.drop_column(TABLE, COLUMN, schema=SCHEMA)


def downgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(COLUMN, sa.Integer(), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        CONSTRAINT,
        TABLE,
        f"{COLUMN} IS NULL OR {COLUMN} >= 0",
        schema=SCHEMA,
    )
