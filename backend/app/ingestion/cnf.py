"""Import hors ligne du FCÉN 2026 vers le registre de candidats.

Usage depuis ``backend/`` :

    python -m app.ingestion.cnf --archive ../data/cnf_fcen_all-files-data_2026.zip

L'import copie fidèlement les champs d'identité bilingues. Il ne crée jamais
d'ingrédient canonique, d'alias approuvé ou de référence externe : ces trois
opérations restent des décisions de curation distinctes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import CnfFoodCandidate, IngredientCandidateStatus
from ..models.base import utcnow

FOOD_NAME_FILE = "Food_Name.csv"
FOOD_GROUP_FILE = "CNF_Food_Group.csv"

FOOD_NAME_COLUMNS = (
    "Food_Code",
    "Food_Description_EN",
    "Food_Description_FR",
    "Alternate_Description_EN",
    "Alternate_Description_FR",
    "Food_Source_Code",
    "USDA_NDB_Code",
    "CNF_Food_Group_Code",
    "Comment_EN",
    "Comment_FR",
    "ScientificName",
    "Food_Last_Updated_Date",
)
FOOD_GROUP_COLUMNS = (
    "CNF_Food_Group_Code",
    "CNF_Food_Group_Description_EN",
    "CNF_Food_Group_Description_FR",
)

# Quarantaine initiale documentée dans docs/ingredient-database-research.md.
# Rien n'est supprimé : un curateur peut réviser chaque décision.
EXCLUDED_GROUP_CODES = frozenset({"3", "19", "21", "22", "25"})
REVIEW_GROUP_CODES = frozenset({"14"})


class CnfImportError(ValueError):
    """Archive absente, schéma inattendu ou donnée d'identité invalide."""


@dataclass(frozen=True)
class ParsedCnfArchive:
    archive_sha256: str
    rows: tuple[dict, ...]

    @property
    def status_counts(self) -> dict[str, int]:
        counts = Counter(row["curation_status"].value for row in self.rows)
        return dict(sorted(counts.items()))


def _member_named(archive: ZipFile, expected_name: str):
    matches = [
        info
        for info in archive.infolist()
        if PurePosixPath(info.filename).name.casefold() == expected_name.casefold()
    ]
    if len(matches) != 1:
        raise CnfImportError(
            f"L'archive doit contenir exactement un fichier {expected_name}; "
            f"trouvé : {len(matches)}."
        )
    return matches[0]


def _read_csv(archive: ZipFile, expected_name: str, required: tuple[str, ...]):
    member = _member_named(archive, expected_name)
    with archive.open(member) as binary:
        with io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as text:
            reader = csv.DictReader(text)
            columns = tuple(reader.fieldnames or ())
            missing = [name for name in required if name not in columns]
            if missing:
                raise CnfImportError(
                    f"Colonnes manquantes dans {expected_name} : {missing}."
                )
            return [dict(row) for row in reader]


def _optional(value: str | None) -> str | None:
    stripped = (value or "").strip()
    return stripped or None


def _initial_status(group_code: str) -> IngredientCandidateStatus:
    if group_code in EXCLUDED_GROUP_CODES:
        return IngredientCandidateStatus.excluded
    if group_code in REVIEW_GROUP_CODES:
        return IngredientCandidateStatus.review
    return IngredientCandidateStatus.candidate


def parse_cnf_archive(
    archive_path: str | Path, source_version: str = "2026"
) -> ParsedCnfArchive:
    """Valide et transforme l'archive officielle en lignes de staging."""
    path = Path(archive_path)
    if not path.is_file():
        raise CnfImportError(f"Archive FCÉN introuvable : {path}")
    archive_sha256 = hashlib.sha256(path.read_bytes()).hexdigest().upper()

    with ZipFile(path) as archive:
        group_rows = _read_csv(archive, FOOD_GROUP_FILE, FOOD_GROUP_COLUMNS)
        food_rows = _read_csv(archive, FOOD_NAME_FILE, FOOD_NAME_COLUMNS)

    groups: dict[str, tuple[str, str]] = {}
    for row in group_rows:
        code = (row["CNF_Food_Group_Code"] or "").strip()
        name_en = (row["CNF_Food_Group_Description_EN"] or "").strip()
        name_fr = (row["CNF_Food_Group_Description_FR"] or "").strip()
        if not code or not name_en or not name_fr:
            raise CnfImportError("Groupe FCÉN incomplet dans CNF_Food_Group.csv.")
        if code in groups:
            raise CnfImportError(f"Code de groupe FCÉN dupliqué : {code}.")
        groups[code] = (name_en, name_fr)

    seen_codes: set[str] = set()
    parsed: list[dict] = []
    for raw in food_rows:
        food_code = (raw["Food_Code"] or "").strip()
        name_en = (raw["Food_Description_EN"] or "").strip()
        name_fr = (raw["Food_Description_FR"] or "").strip()
        group_code = (raw["CNF_Food_Group_Code"] or "").strip()
        if not food_code or not name_en or not name_fr or not group_code:
            raise CnfImportError(
                "Chaque aliment FCÉN doit avoir un code, deux descriptions "
                "primaires et un groupe."
            )
        if food_code in seen_codes:
            raise CnfImportError(f"Food_Code dupliqué : {food_code}.")
        if group_code not in groups:
            raise CnfImportError(
                f"Groupe FCÉN inconnu {group_code} pour Food_Code {food_code}."
            )
        seen_codes.add(food_code)
        group_en, group_fr = groups[group_code]
        parsed.append(
            {
                "source_version": source_version,
                "archive_sha256": archive_sha256,
                "food_code": food_code,
                "food_description_en": name_en,
                "food_description_fr": name_fr,
                "alternate_description_en": _optional(
                    raw["Alternate_Description_EN"]
                ),
                "alternate_description_fr": _optional(
                    raw["Alternate_Description_FR"]
                ),
                "food_source_code": _optional(raw["Food_Source_Code"]),
                "usda_ndb_code": _optional(raw["USDA_NDB_Code"]),
                "cnf_food_group_code": group_code,
                "cnf_food_group_description_en": group_en,
                "cnf_food_group_description_fr": group_fr,
                "comment_en": _optional(raw["Comment_EN"]),
                "comment_fr": _optional(raw["Comment_FR"]),
                "scientific_name": _optional(raw["ScientificName"]),
                "food_last_updated_date": _optional(
                    raw["Food_Last_Updated_Date"]
                ),
                "raw_payload": raw,
                "curation_status": _initial_status(group_code),
            }
        )
    return ParsedCnfArchive(archive_sha256, tuple(parsed))


def upsert_cnf_candidates(
    session: Session, parsed: ParsedCnfArchive, batch_size: int = 250
) -> int:
    """Upsert PostgreSQL idempotent sans écraser les décisions de curation."""
    source_fields = (
        "archive_sha256",
        "food_description_en",
        "food_description_fr",
        "alternate_description_en",
        "alternate_description_fr",
        "food_source_code",
        "usda_ndb_code",
        "cnf_food_group_code",
        "cnf_food_group_description_en",
        "cnf_food_group_description_fr",
        "comment_en",
        "comment_fr",
        "scientific_name",
        "food_last_updated_date",
        "raw_payload",
    )
    rows = list(parsed.rows)
    for offset in range(0, len(rows), batch_size):
        now = utcnow()
        batch = [
            {**row, "created_at": now, "updated_at": now}
            for row in rows[offset : offset + batch_size]
        ]
        stmt = pg_insert(CnfFoodCandidate).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["source_version", "food_code"],
            set_={
                **{field: getattr(stmt.excluded, field) for field in source_fields},
                "updated_at": now,
            },
        )
        session.execute(stmt)
    return len(rows)


def import_cnf_archive(
    session: Session, archive_path: str | Path, source_version: str = "2026"
) -> ParsedCnfArchive:
    parsed = parse_cnf_archive(archive_path, source_version=source_version)
    upsert_cnf_candidates(session, parsed)
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--source-version", default="2026")
    args = parser.parse_args()

    with SessionLocal() as session:
        parsed = import_cnf_archive(
            session, args.archive, source_version=args.source_version
        )
        session.commit()
    print(
        f"FCÉN {args.source_version} : {len(parsed.rows)} candidats importés; "
        f"statuts initiaux={parsed.status_counts}; sha256={parsed.archive_sha256}"
    )


if __name__ == "__main__":
    main()
