"""Fixtures de base de données de test (module partagé).

Une base ``menu_test`` dédiée est migrée par Alembic puis seedée avec
l'instance jouet ; les tests API tournent contre elle via le TestClient avec
la session injectée. Si PostgreSQL est injoignable, les tests DB sont sautés
proprement (le reste de la suite reste exécutable partout).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import sqlalchemy
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session, sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
SEED_TOY = BACKEND.parent / "seed" / "toy"
TEST_URL = os.environ.get(
    "MENU_TEST_DATABASE_URL",
    "postgresql+psycopg2://menu:menu@localhost:5432/menu_test",
)
ADMIN_URL = TEST_URL.rsplit("/", 1)[0] + "/menu_optimizer"


@pytest.fixture(scope="session")
def test_engine():
    try:
        admin = sqlalchemy.create_engine(
            ADMIN_URL, isolation_level="AUTOCOMMIT"
        )
        with admin.connect() as conn:
            exists = conn.execute(
                sqlalchemy.text(
                    "SELECT 1 FROM pg_database WHERE datname = 'menu_test'"
                )
            ).scalar()
            if not exists:
                conn.execute(sqlalchemy.text("CREATE DATABASE menu_test"))
    except sqlalchemy.exc.OperationalError:
        pytest.skip("PostgreSQL injoignable : tests DB sautés.")

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    engine = sqlalchemy.create_engine(TEST_URL, future=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def toy_seeded(test_engine):
    """Seed jouet chargé une fois par session de test, via le pipeline réel
    (ports JSON → staging → normalisation)."""
    from app.seeding.seed import run

    factory = sessionmaker(bind=test_engine, class_=Session,
                           expire_on_commit=False)
    run(str(SEED_TOY), session_factory=factory)
    return factory


@pytest.fixture
def db_session(toy_seeded, test_engine):
    """Session par test ; les tables mutables (plans, essentiels) sont
    remises à l'état seedé après chaque test."""
    factory = toy_seeded
    with factory() as session:
        yield session
        session.rollback()
    with factory() as cleanup:
        cleanup.execute(sqlalchemy.text("DELETE FROM household.plan"))
        cleanup.execute(sqlalchemy.text("DELETE FROM household.staple"))
        cleanup.commit()


@pytest.fixture
def api_client(db_session):
    """TestClient avec session ET solveur injectés — le solveur reste le vrai
    PuLP par défaut ; les tests de substituabilité le remplacent."""
    from fastapi.testclient import TestClient

    from app.api.deps import get_session
    from app.main import app

    def override_session():
        yield db_session
        db_session.commit()

    app.dependency_overrides[get_session] = override_session
    yield TestClient(app)
    app.dependency_overrides.clear()
