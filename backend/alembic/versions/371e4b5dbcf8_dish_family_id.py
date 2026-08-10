"""dish family id

Revision ID: 371e4b5dbcf8
Revises: 7608d703d502
Create Date: 2026-08-10 17:29:00.275422

D16 (docs/deviations.md) : les variantes d'échelle (format régulier /
familial) du seed partagent un même plat mais étaient traitées comme deux
recettes sans lien par le solveur, le compte de diversité et la pénalité de
répétition. Cette migration ajoute ``catalog.recipe.dish_family_id`` et
rétro-remplit les 40 lignes existantes du seed principal depuis la
convention de nommage ``<id>`` / ``<id>_familial`` (même dérivation que le
seeding, ``app.services.dish_family.dish_family_id_of`` — importée ici pour
qu'il n'existe qu'une seule implémentation de la convention).
"""
from alembic import op
import sqlalchemy as sa

revision = '371e4b5dbcf8'
down_revision = '7608d703d502'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'recipe',
        sa.Column('dish_family_id', sa.String(length=64), nullable=True),
        schema='catalog',
    )

    from app.services.dish_family import dish_family_id_of

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id FROM catalog.recipe")).fetchall()
    for (recipe_id,) in rows:
        bind.execute(
            sa.text(
                "UPDATE catalog.recipe SET dish_family_id = :family "
                "WHERE id = :recipe_id"
            ),
            {"family": dish_family_id_of(recipe_id), "recipe_id": recipe_id},
        )

    op.alter_column(
        'recipe', 'dish_family_id', nullable=False, schema='catalog'
    )
    op.create_index(
        'ix_recipe_dish_family_id', 'recipe', ['dish_family_id'],
        schema='catalog',
    )


def downgrade() -> None:
    op.drop_index(
        'ix_recipe_dish_family_id', table_name='recipe', schema='catalog'
    )
    op.drop_column('recipe', 'dish_family_id', schema='catalog')
