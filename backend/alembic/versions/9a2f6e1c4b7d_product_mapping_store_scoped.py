"""product_mapping store-scoped, resolves to product

Revision ID: 9a2f6e1c4b7d
Revises: 371e4b5dbcf8
Create Date: 2026-08-11 00:00:00.000000

D18 (docs/deviations.md), résolution de D15 : ``market.product_mapping``
mappait ``raw_text`` seul vers ``canonical_ingredient_id``. Deux défauts :
(1) un même libellé peut désigner des produits différents (marque, format,
prix) d'une bannière à l'autre — la clé doit être ``(store_id, raw_text)`` ;
(2) le solveur a besoin d'un produit précis (v_p), pas seulement d'un
ingrédient canonique — la colonne cible doit être ``product_id``.

Aucune donnée de seed ne peuple jamais cette table avec un mapping réel (le
seed résout toujours via ``product_external_key`` sans jamais passer par
``product_mapping``) ; les lignes existantes d'une base de dev seraient au
mieux des placeholders ``product_id`` NULL sans magasin déductible depuis le
schéma actuel, donc supprimées avant d'ajouter ``store_id NOT NULL``.

Garde de sécurité : si une base porte des lignes ``confirmed_by IS NOT
NULL`` (une confirmation manuelle passée par ``POST /api/ingredients/map``
avant ce correctif), la migration s'arrête avec une erreur explicite plutôt
que de les détruire silencieusement — exporter ces lignes à la main
(``SELECT * FROM market.product_mapping WHERE confirmed_by IS NOT NULL``)
avant de rejouer.
"""
from alembic import op
import sqlalchemy as sa

revision = '9a2f6e1c4b7d'
down_revision = '371e4b5dbcf8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    confirmed_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM market.product_mapping "
            "WHERE confirmed_by IS NOT NULL"
        )
    ).scalar()
    if confirmed_count:
        raise RuntimeError(
            f"{confirmed_count} ligne(s) de market.product_mapping ont "
            "confirmed_by renseigné (confirmation manuelle passée par "
            "l'API avant ce correctif) — cette migration les supprimerait. "
            "Exporte-les d'abord "
            "(SELECT * FROM market.product_mapping WHERE confirmed_by IS "
            "NOT NULL) puis rejoue la migration."
        )

    op.execute("DELETE FROM market.product_mapping")

    op.drop_constraint(
        'uq_product_mapping_raw_text', 'product_mapping', schema='market',
        type_='unique',
    )
    op.drop_constraint(
        'fk_product_mapping_canonical_ingredient_id_canonical_ingredient',
        'product_mapping', schema='market', type_='foreignkey',
    )
    op.drop_column('product_mapping', 'canonical_ingredient_id', schema='market')

    op.add_column(
        'product_mapping',
        sa.Column('store_id', sa.Integer(), nullable=False),
        schema='market',
    )
    op.create_foreign_key(
        'fk_product_mapping_store_id_store', 'product_mapping', 'store',
        ['store_id'], ['id'], source_schema='market', referent_schema='market',
    )
    op.add_column(
        'product_mapping',
        sa.Column('product_id', sa.Integer(), nullable=True),
        schema='market',
    )
    op.create_foreign_key(
        'fk_product_mapping_product_id_product', 'product_mapping', 'product',
        ['product_id'], ['id'], source_schema='market', referent_schema='market',
    )
    op.create_unique_constraint(
        'uq_product_mapping_store_id_raw_text', 'product_mapping',
        ['store_id', 'raw_text'], schema='market',
    )


def downgrade() -> None:
    op.drop_constraint(
        'uq_product_mapping_store_id_raw_text', 'product_mapping',
        schema='market', type_='unique',
    )
    op.drop_constraint(
        'fk_product_mapping_product_id_product', 'product_mapping',
        schema='market', type_='foreignkey',
    )
    op.drop_column('product_mapping', 'product_id', schema='market')
    op.drop_constraint(
        'fk_product_mapping_store_id_store', 'product_mapping',
        schema='market', type_='foreignkey',
    )
    op.drop_column('product_mapping', 'store_id', schema='market')

    op.add_column(
        'product_mapping',
        sa.Column('canonical_ingredient_id', sa.String(length=64), nullable=True),
        schema='market',
    )
    op.create_foreign_key(
        'fk_product_mapping_canonical_ingredient_id_canonical_ingredient',
        'product_mapping', 'canonical_ingredient',
        ['canonical_ingredient_id'], ['id'],
        source_schema='market', referent_schema='catalog',
    )
    op.create_unique_constraint(
        'uq_product_mapping_raw_text', 'product_mapping', ['raw_text'],
        schema='market',
    )
