"""Import bilingue et idempotent du FCÉN vers staging."""

from __future__ import annotations

import csv
import io
from zipfile import ZipFile

import pytest
from sqlalchemy import func, select

from app.ingestion.cnf import (
    FOOD_GROUP_COLUMNS,
    FOOD_NAME_COLUMNS,
    CnfImportError,
    import_cnf_archive,
    parse_cnf_archive,
)
from app.models import CnfFoodCandidate, IngredientCandidateStatus
from tests.db_fixtures import db_session, test_engine, toy_seeded  # noqa: F401


def _csv_bytes(columns, rows) -> bytes:
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + text.getvalue()).encode("utf-8")


def _archive(tmp_path, foods):
    groups = [
        {
            "CNF_Food_Group_Code": "1",
            "CNF_Food_Group_Description_EN": "Dairy and Egg Products",
            "CNF_Food_Group_Description_FR": "Produits laitiers et œufs",
        },
        {
            "CNF_Food_Group_Code": "3",
            "CNF_Food_Group_Description_EN": "Babyfoods",
            "CNF_Food_Group_Description_FR": "Aliments pour bébés",
        },
        {
            "CNF_Food_Group_Code": "14",
            "CNF_Food_Group_Description_EN": "Beverages",
            "CNF_Food_Group_Description_FR": "Boissons",
        },
    ]
    path = tmp_path / "cnf_2026.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "nested/CNF_Food_Group.csv",
            _csv_bytes(FOOD_GROUP_COLUMNS, groups),
        )
        archive.writestr(
            "nested/Food_Name.csv", _csv_bytes(FOOD_NAME_COLUMNS, foods)
        )
    return path


def _food(code="101", group="1", name_fr="Œuf entier"):
    return {
        "Food_Code": code,
        "Food_Description_EN": "Whole egg",
        "Food_Description_FR": name_fr,
        "Alternate_Description_EN": "Egg",
        "Alternate_Description_FR": "Œuf",
        "Food_Source_Code": "1",
        "USDA_NDB_Code": "01123",
        "CNF_Food_Group_Code": group,
        "Comment_EN": "Raw",
        "Comment_FR": "Cru",
        "ScientificName": "Gallus gallus",
        "Food_Last_Updated_Date": "2026-01-15",
    }


def test_parse_cnf_archive_preserves_french_and_assigns_initial_statuses(tmp_path):
    path = _archive(
        tmp_path,
        [
            _food("101", "1"),
            _food("102", "14", "Jus de citron"),
            _food("103", "3", "Purée pour bébé"),
        ],
    )

    parsed = parse_cnf_archive(path)

    assert parsed.archive_sha256 == parsed.archive_sha256.upper()
    assert len(parsed.archive_sha256) == 64
    assert [row["food_description_fr"] for row in parsed.rows] == [
        "Œuf entier",
        "Jus de citron",
        "Purée pour bébé",
    ]
    assert [row["curation_status"] for row in parsed.rows] == [
        IngredientCandidateStatus.candidate,
        IngredientCandidateStatus.review,
        IngredientCandidateStatus.excluded,
    ]
    assert parsed.status_counts == {"candidate": 1, "excluded": 1, "review": 1}


def test_parse_cnf_archive_rejects_missing_french_identity(tmp_path):
    path = _archive(tmp_path, [_food(name_fr="")])

    with pytest.raises(CnfImportError, match="deux descriptions"):
        parse_cnf_archive(path)


def test_import_is_idempotent_and_preserves_human_status(db_session, tmp_path):
    path = _archive(tmp_path, [_food()])

    import_cnf_archive(db_session, path, source_version="test-2026")
    candidate = db_session.scalar(
        select(CnfFoodCandidate).where(
            CnfFoodCandidate.source_version == "test-2026"
        )
    )
    candidate.curation_status = IngredientCandidateStatus.approved
    candidate.reviewed_by = "testeur"
    db_session.flush()

    import_cnf_archive(db_session, path, source_version="test-2026")
    db_session.expire_all()

    count = db_session.scalar(
        select(func.count()).select_from(CnfFoodCandidate).where(
            CnfFoodCandidate.source_version == "test-2026"
        )
    )
    candidate = db_session.scalar(
        select(CnfFoodCandidate).where(
            CnfFoodCandidate.source_version == "test-2026"
        )
    )
    assert count == 1
    assert candidate.food_description_fr == "Œuf entier"
    assert candidate.curation_status == IngredientCandidateStatus.approved
    assert candidate.reviewed_by == "testeur"
