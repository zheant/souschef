"""Ingredient families and auditable curation decisions.

Revision ID: b7e1d4a9c2f6
Revises: f4a7c9d2e6b1
Create Date: 2026-08-12 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b7e1d4a9c2f6"
down_revision = "f4a7c9d2e6b1"
branch_labels = None
depends_on = None

_ACTION_VALUES = ("attach_existing", "create_variant", "exclude")


def _action_type(*, create_type: bool = True) -> postgresql.ENUM:
    return postgresql.ENUM(
        *_ACTION_VALUES,
        name="ingredient_curation_action",
        schema="catalog",
        create_type=create_type,
    )


def upgrade() -> None:
    op.create_table(
        "ingredient_family",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name_fr", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120), nullable=True),
        sa.Column("description_fr", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingredient_family")),
        schema="catalog",
    )
    op.add_column(
        "canonical_ingredient",
        sa.Column("family_id", sa.String(length=64), nullable=True),
        schema="catalog",
    )
    op.create_foreign_key(
        op.f("fk_canonical_ingredient_family_id_ingredient_family"),
        "canonical_ingredient",
        "ingredient_family",
        ["family_id"],
        ["id"],
        source_schema="catalog",
        referent_schema="catalog",
    )
    op.create_index(
        "ix_canonical_ingredient_family_id",
        "canonical_ingredient",
        ["family_id"],
        schema="catalog",
    )

    _action_type().create(op.get_bind(), checkfirst=True)
    action_type = _action_type(create_type=False)
    op.create_table(
        "ingredient_curation_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("decision_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_version", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("source_archive_sha256", sa.String(length=64), nullable=False),
        sa.Column("action", action_type, nullable=False),
        sa.Column(
            "canonical_ingredient_id", sa.String(length=64), nullable=True
        ),
        sa.Column("reviewer", sa.String(length=120), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("decision_payload", postgresql.JSONB(), nullable=False),
        sa.Column("candidate_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(action = 'exclude' AND canonical_ingredient_id IS NULL) OR "
            "(action <> 'exclude' AND canonical_ingredient_id IS NOT NULL)",
            name=op.f("ck_ingredient_curation_event_target_matches_action"),
        ),
        sa.ForeignKeyConstraint(
            ["canonical_ingredient_id"],
            ["catalog.canonical_ingredient.id"],
            name=op.f(
                "fk_ingredient_curation_event_canonical_ingredient_id_"
                "canonical_ingredient"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_ingredient_curation_event")
        ),
        sa.UniqueConstraint(
            "decision_fingerprint",
            name=op.f(
                "uq_ingredient_curation_event_decision_fingerprint"
            ),
        ),
        schema="catalog",
    )
    op.create_index(
        "ix_ingredient_curation_event_source_key",
        "ingredient_curation_event",
        ["source", "source_version", "external_id"],
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ingredient_curation_event_source_key",
        table_name="ingredient_curation_event",
        schema="catalog",
    )
    op.drop_table("ingredient_curation_event", schema="catalog")
    _action_type().drop(op.get_bind(), checkfirst=True)
    op.drop_constraint(
        op.f("fk_canonical_ingredient_family_id_ingredient_family"),
        "canonical_ingredient",
        schema="catalog",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_canonical_ingredient_family_id",
        table_name="canonical_ingredient",
        schema="catalog",
    )
    op.drop_column("canonical_ingredient", "family_id", schema="catalog")
    op.drop_table("ingredient_family", schema="catalog")
