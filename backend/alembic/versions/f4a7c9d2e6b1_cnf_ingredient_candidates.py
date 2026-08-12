"""FCÉN ingredient candidates, approved aliases and external references.

Revision ID: f4a7c9d2e6b1
Revises: c3d8f21a9e6b
Create Date: 2026-08-12 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f4a7c9d2e6b1"
down_revision = "f4b1a9d0c2e6"
branch_labels = None
depends_on = None

_STATUS_VALUES = ("candidate", "review", "excluded", "approved", "rejected")


def _status_type(*, create_type: bool = True) -> postgresql.ENUM:
    return postgresql.ENUM(
        *_STATUS_VALUES,
        name="ingredient_candidate_status",
        schema="staging",
        create_type=create_type,
    )


def upgrade() -> None:
    _status_type().create(op.get_bind(), checkfirst=True)
    status_type = _status_type(create_type=False)

    op.create_table(
        "cnf_food_candidate",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_version", sa.String(length=32), nullable=False),
        sa.Column("archive_sha256", sa.String(length=64), nullable=False),
        sa.Column("food_code", sa.String(length=32), nullable=False),
        sa.Column("food_description_en", sa.Text(), nullable=False),
        sa.Column("food_description_fr", sa.Text(), nullable=False),
        sa.Column("alternate_description_en", sa.Text(), nullable=True),
        sa.Column("alternate_description_fr", sa.Text(), nullable=True),
        sa.Column("food_source_code", sa.String(length=32), nullable=True),
        sa.Column("usda_ndb_code", sa.String(length=32), nullable=True),
        sa.Column("cnf_food_group_code", sa.String(length=16), nullable=False),
        sa.Column("cnf_food_group_description_en", sa.Text(), nullable=False),
        sa.Column("cnf_food_group_description_fr", sa.Text(), nullable=False),
        sa.Column("comment_en", sa.Text(), nullable=True),
        sa.Column("comment_fr", sa.Text(), nullable=True),
        sa.Column("scientific_name", sa.Text(), nullable=True),
        sa.Column("food_last_updated_date", sa.String(length=32), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "curation_status",
            status_type,
            server_default="candidate",
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.String(length=120), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cnf_food_candidate")),
        sa.UniqueConstraint(
            "source_version",
            "food_code",
            name=op.f("uq_cnf_food_candidate_source_version_food_code"),
        ),
        schema="staging",
    )
    op.create_index(
        "ix_cnf_food_candidate_status",
        "cnf_food_candidate",
        ["curation_status"],
        schema="staging",
    )
    op.create_index(
        "ix_cnf_food_candidate_group",
        "cnf_food_candidate",
        ["cnf_food_group_code"],
        schema="staging",
    )

    op.create_table(
        "canonical_ingredient_alias",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "canonical_ingredient_id", sa.String(length=64), nullable=False
        ),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("normalized_alias", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_version", sa.String(length=32), nullable=True),
        sa.Column("confirmed_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["canonical_ingredient_id"],
            ["catalog.canonical_ingredient.id"],
            name=op.f(
                "fk_canonical_ingredient_alias_canonical_ingredient_id_canonical_ingredient"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_canonical_ingredient_alias")
        ),
        sa.UniqueConstraint(
            "language",
            "normalized_alias",
            name=op.f(
                "uq_canonical_ingredient_alias_language_normalized_alias"
            ),
        ),
        schema="catalog",
    )

    op.create_table(
        "canonical_ingredient_external_ref",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "canonical_ingredient_id", sa.String(length=64), nullable=False
        ),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("source_version", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["canonical_ingredient_id"],
            ["catalog.canonical_ingredient.id"],
            name=op.f(
                "fk_canonical_ingredient_external_ref_canonical_ingredient_id_canonical_ingredient"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_canonical_ingredient_external_ref")
        ),
        sa.UniqueConstraint(
            "source",
            "external_id",
            "source_version",
            name=op.f(
                "uq_canonical_ingredient_external_ref_source_external_id_source_version"
            ),
        ),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_table("canonical_ingredient_external_ref", schema="catalog")
    op.drop_table("canonical_ingredient_alias", schema="catalog")
    op.drop_index(
        "ix_cnf_food_candidate_group",
        table_name="cnf_food_candidate",
        schema="staging",
    )
    op.drop_index(
        "ix_cnf_food_candidate_status",
        table_name="cnf_food_candidate",
        schema="staging",
    )
    op.drop_table("cnf_food_candidate", schema="staging")
    _status_type().drop(op.get_bind(), checkfirst=True)
