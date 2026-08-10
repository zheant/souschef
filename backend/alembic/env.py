"""Environnement Alembic — migrations multi-schémas (catalog, market, household, staging)."""

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.models import Base, SCHEMAS  # noqa: F401 — enregistre toutes les tables

config = context.config
if os.environ.get("MENU_DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.environ["MENU_DATABASE_URL"])

target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    # Ne considérer que nos quatre schémas (ignore public et extensions).
    if type_ == "schema":
        return name in SCHEMAS
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
