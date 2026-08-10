"""D16 (docs/deviations.md) : détection de dérive de household_profile en
base par rapport au seed versionné — vérifié contre PostgreSQL réel."""

import json
from pathlib import Path

import sqlalchemy

from app.seeding.check_profile_drift import check
from tests.db_fixtures import test_engine, toy_seeded  # noqa: F401

TOY = Path(__file__).resolve().parents[2] / "seed" / "toy"


def test_no_drift_right_after_seeding(toy_seeded):
    assert check(str(TOY), profile_id="default", session_factory=toy_seeded) == []


def test_drift_detected_and_reported(toy_seeded):
    original = json.loads(
        (TOY / "household.json").read_text()
    )["profile"]["min_distinct_recipes"]
    drifted = original + 50
    with toy_seeded() as session:
        session.execute(
            sqlalchemy.text(
                "UPDATE household.household_profile "
                "SET min_distinct_recipes = :v WHERE id = 'default'"
            ),
            {"v": drifted},
        )
        session.commit()
    try:
        drift = check(str(TOY), profile_id="default", session_factory=toy_seeded)
        fields = {name: (seed_v, db_v) for name, seed_v, db_v in drift}
        assert fields["min_distinct_recipes"] == (original, drifted)
    finally:
        with toy_seeded() as session:
            session.execute(
                sqlalchemy.text(
                    "UPDATE household.household_profile "
                    "SET min_distinct_recipes = :v WHERE id = 'default'"
                ),
                {"v": original},
            )
            session.commit()
    # La restauration s'est bien produite : plus de dérive détectée.
    assert check(str(TOY), profile_id="default", session_factory=toy_seeded) == []


def test_missing_profile_is_not_reported_as_drift(toy_seeded):
    """Un profil absent en base (id inconnu) n'est pas une dérive à
    signaler — seul un profil présent ET différent l'est."""
    drift = check(str(TOY), profile_id="profil_inexistant", session_factory=toy_seeded)
    assert drift == []
