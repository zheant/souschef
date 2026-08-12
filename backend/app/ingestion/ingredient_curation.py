"""Curation hors ligne des candidats FCÉN vers le catalogue canonique.

Le module reste dans la couche ingestion parce qu'il est le seul pont entre
``staging`` et ``catalog``. Il s'exécute en lot, jamais dans une requête HTTP.

Exemples depuis ``backend/``::

    python -m app.ingestion.ingredient_curation preview \
        --source-version 2026 --food-code 1234
    python -m app.ingestion.ingredient_curation apply \
        --manifest ../data/curation-riz.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import (
    CanonicalIngredient,
    CanonicalIngredientAlias,
    CanonicalIngredientExternalRef,
    CnfFoodCandidate,
    IngredientCandidateStatus,
    IngredientCurationAction,
    IngredientCurationEvent,
    IngredientFamily,
    UnitKind,
)
from ..models.base import utcnow

SOURCE = "cnf"
SIMILARITY_THRESHOLD = 0.72
_SLUG = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


class CurationError(ValueError):
    """Manifeste invalide ou décision qui violerait le canon."""


class CandidateNotFound(CurationError):
    pass


class CanonicalIngredientNotFound(CurationError):
    pass


class DuplicateCanonicalError(CurationError):
    pass


class SimilarCandidatesNeedReview(CurationError):
    pass


@dataclass(frozen=True)
class AliasSpec:
    language: str
    alias: str


@dataclass(frozen=True)
class CanonicalSpec:
    id: str
    family_id: str
    name: str
    unit_kind: UnitKind
    base_unit: str
    perishability: Decimal | None = None
    salvage_value_cents_per_base_unit: Decimal | None = None
    density_g_per_ml: Decimal | None = None


@dataclass(frozen=True)
class CurationDecision:
    source_version: str
    food_code: str
    action: IngredientCurationAction
    reviewer: str
    rationale: str
    canonical_ingredient_id: str | None = None
    canonical: CanonicalSpec | None = None
    aliases: tuple[AliasSpec, ...] = ()
    acknowledged_similar_ids: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        canonical = None
        if self.canonical is not None:
            canonical = {
                **asdict(self.canonical),
                "unit_kind": self.canonical.unit_kind.value,
                "perishability": (
                    str(self.canonical.perishability)
                    if self.canonical.perishability is not None else None
                ),
                "salvage_value_cents_per_base_unit": (
                    str(self.canonical.salvage_value_cents_per_base_unit)
                    if self.canonical.salvage_value_cents_per_base_unit is not None
                    else None
                ),
                "density_g_per_ml": (
                    str(self.canonical.density_g_per_ml)
                    if self.canonical.density_g_per_ml is not None
                    else None
                ),
            }
        return {
            "source_version": self.source_version,
            "food_code": self.food_code,
            "action": self.action.value,
            "reviewer": self.reviewer,
            "rationale": self.rationale,
            "canonical_ingredient_id": self.canonical_ingredient_id,
            "canonical": canonical,
            "aliases": [asdict(alias) for alias in self.aliases],
            "acknowledged_similar_ids": sorted(
                set(self.acknowledged_similar_ids)
            ),
        }


@dataclass(frozen=True)
class Match:
    canonical_ingredient_id: str
    canonical_name: str
    matched_label: str
    candidate_label: str
    score: float
    exact: bool


@dataclass(frozen=True)
class CandidatePreview:
    source_version: str
    food_code: str
    name_fr: str
    name_en: str
    initial_status: str
    exact_matches: tuple[Match, ...]
    similar_matches: tuple[Match, ...]


@dataclass(frozen=True)
class ApplyResult:
    event_id: int
    action: str
    canonical_ingredient_id: str | None
    replayed: bool


def normalize_label(value: str) -> str:
    """Normalisation déterministe pour les collisions, jamais affichée."""
    expanded = value.casefold().translate(
        str.maketrans({"œ": "oe", "æ": "ae", "ß": "ss"})
    )
    decomposed = unicodedata.normalize("NFKD", expanded)
    without_marks = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return " ".join(re.findall(r"[a-z0-9]+", without_marks))


def label_similarity(left: str, right: str) -> float:
    left_n, right_n = normalize_label(left), normalize_label(right)
    if not left_n or not right_n:
        return 0.0
    if left_n == right_n:
        return 1.0
    shorter, longer = sorted((left_n, right_n), key=len)
    if len(shorter.split()) >= 2 and shorter in longer:
        return 0.95
    return SequenceMatcher(None, left_n, right_n).ratio()


def preview_candidate(
    session: Session,
    source_version: str,
    food_code: str,
    *,
    threshold: float = SIMILARITY_THRESHOLD,
) -> CandidatePreview:
    candidate = _load_candidate(session, source_version, food_code)
    labels = _candidate_labels(candidate)
    matches = _matches(session, labels, threshold=threshold)
    return CandidatePreview(
        source_version=source_version,
        food_code=food_code,
        name_fr=candidate.food_description_fr,
        name_en=candidate.food_description_en,
        initial_status=candidate.curation_status.value,
        exact_matches=tuple(match for match in matches if match.exact),
        similar_matches=tuple(match for match in matches if not match.exact),
    )


def apply_decision(session: Session, decision: CurationDecision) -> ApplyResult:
    _validate_decision(decision)
    candidate = _load_candidate(
        session, decision.source_version, decision.food_code
    )
    payload = decision.payload()
    fingerprint = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest().upper()
    prior = session.scalar(
        select(IngredientCurationEvent).where(
            IngredientCurationEvent.decision_fingerprint == fingerprint
        )
    )
    if prior is not None:
        return ApplyResult(
            event_id=prior.id,
            action=prior.action.value,
            canonical_ingredient_id=prior.canonical_ingredient_id,
            replayed=True,
        )

    target_id: str | None = None
    if decision.action == IngredientCurationAction.attach_existing:
        target_id = decision.canonical_ingredient_id
        if session.get(CanonicalIngredient, target_id) is None:
            raise CanonicalIngredientNotFound(
                f"Ingrédient canonique '{target_id}' introuvable."
            )
    elif decision.action == IngredientCurationAction.create_variant:
        spec = decision.canonical
        assert spec is not None  # validé par _validate_decision
        _create_variant(session, candidate, spec, decision)
        target_id = spec.id

    if target_id is not None:
        _attach_external_ref(session, candidate, target_id, decision.rationale)
        _approve_aliases(session, target_id, decision.aliases, decision)

    now = utcnow()
    event = IngredientCurationEvent(
        decision_fingerprint=fingerprint,
        source=SOURCE,
        source_version=decision.source_version,
        external_id=decision.food_code,
        source_archive_sha256=candidate.archive_sha256,
        action=decision.action,
        canonical_ingredient_id=target_id,
        reviewer=decision.reviewer,
        rationale=decision.rationale,
        decision_payload=payload,
        candidate_snapshot=_candidate_snapshot(candidate),
        decided_at=now,
    )
    session.add(event)
    candidate.curation_status = (
        IngredientCandidateStatus.rejected
        if decision.action == IngredientCurationAction.exclude
        else IngredientCandidateStatus.approved
    )
    candidate.reviewed_by = decision.reviewer
    candidate.reviewed_at = now
    session.flush()
    return ApplyResult(
        event_id=event.id,
        action=decision.action.value,
        canonical_ingredient_id=target_id,
        replayed=False,
    )


def _create_variant(
    session: Session,
    candidate: CnfFoodCandidate,
    spec: CanonicalSpec,
    decision: CurationDecision,
) -> None:
    if session.get(CanonicalIngredient, spec.id) is not None:
        raise DuplicateCanonicalError(
            f"L'id canonique '{spec.id}' existe déjà; utiliser attach_existing."
        )
    if session.get(IngredientFamily, spec.family_id) is None:
        raise CurationError(f"Famille '{spec.family_id}' introuvable.")

    labels = [spec.name, *_candidate_labels(candidate)]
    labels.extend(alias.alias for alias in decision.aliases)
    matches = _matches(session, labels, threshold=SIMILARITY_THRESHOLD)
    exact_ids = sorted({match.canonical_ingredient_id for match in matches if match.exact})
    if exact_ids:
        raise DuplicateCanonicalError(
            "Un nom canonique ou alias normalisé existe déjà sur : "
            + ", ".join(exact_ids)
            + "; utiliser attach_existing."
        )
    similar_ids = {match.canonical_ingredient_id for match in matches}
    unacknowledged = sorted(
        similar_ids - set(decision.acknowledged_similar_ids)
    )
    if unacknowledged:
        raise SimilarCandidatesNeedReview(
            "Candidats similaires à réviser (ajouter leurs ids à "
            "acknowledged_similar_ids pour confirmer une variante distincte) : "
            + ", ".join(unacknowledged)
        )

    session.add(
        CanonicalIngredient(
            id=spec.id,
            family_id=spec.family_id,
            name=spec.name,
            unit_kind=spec.unit_kind,
            base_unit=spec.base_unit,
            perishability=spec.perishability,
            salvage_value_cents_per_base_unit=(
                spec.salvage_value_cents_per_base_unit
            ),
            density_g_per_ml=spec.density_g_per_ml,
        )
    )
    session.flush()


def _matches(
    session: Session, labels: list[str], *, threshold: float
) -> tuple[Match, ...]:
    canonical_rows = session.execute(
        select(CanonicalIngredient.id, CanonicalIngredient.name)
    ).all()
    alias_rows = session.execute(
        select(
            CanonicalIngredientAlias.canonical_ingredient_id,
            CanonicalIngredientAlias.alias,
        )
    ).all()
    names = {row.id: row.name for row in canonical_rows}
    searchable = [(row.id, row.name) for row in canonical_rows]
    searchable.extend((row.canonical_ingredient_id, row.alias) for row in alias_rows)

    best: dict[str, Match] = {}
    for candidate_label in labels:
        for canonical_id, matched_label in searchable:
            score = label_similarity(candidate_label, matched_label)
            if score < threshold:
                continue
            match = Match(
                canonical_ingredient_id=canonical_id,
                canonical_name=names[canonical_id],
                matched_label=matched_label,
                candidate_label=candidate_label,
                score=round(score, 4),
                exact=score == 1.0,
            )
            current = best.get(canonical_id)
            if current is None or match.score > current.score:
                best[canonical_id] = match
    return tuple(
        sorted(
            best.values(),
            key=lambda match: (-match.score, match.canonical_ingredient_id),
        )
    )


def _approve_aliases(
    session: Session,
    target_id: str,
    aliases: tuple[AliasSpec, ...],
    decision: CurationDecision,
) -> None:
    canonical_names = session.execute(
        select(CanonicalIngredient.id, CanonicalIngredient.name)
    ).all()
    names_by_normalized: dict[str, str] = {}
    for row in canonical_names:
        names_by_normalized.setdefault(normalize_label(row.name), row.id)

    for alias in aliases:
        normalized = normalize_label(alias.alias)
        name_owner = names_by_normalized.get(normalized)
        if name_owner is not None:
            if name_owner != target_id:
                raise DuplicateCanonicalError(
                    f"L'alias '{alias.alias}' est déjà le nom de '{name_owner}'."
                )
            continue  # un alias identique au nom canonique est redondant
        existing = session.scalar(
            select(CanonicalIngredientAlias).where(
                CanonicalIngredientAlias.language == alias.language,
                CanonicalIngredientAlias.normalized_alias == normalized,
            )
        )
        if existing is not None:
            if existing.canonical_ingredient_id != target_id:
                raise DuplicateCanonicalError(
                    f"L'alias '{alias.alias}' pointe déjà vers "
                    f"'{existing.canonical_ingredient_id}'."
                )
            continue
        session.add(
            CanonicalIngredientAlias(
                canonical_ingredient_id=target_id,
                language=alias.language,
                alias=alias.alias.strip(),
                normalized_alias=normalized,
                source=SOURCE,
                source_version=decision.source_version,
                confirmed_by=decision.reviewer,
            )
        )


def _attach_external_ref(
    session: Session,
    candidate: CnfFoodCandidate,
    target_id: str,
    rationale: str,
) -> None:
    ref = session.scalar(
        select(CanonicalIngredientExternalRef).where(
            CanonicalIngredientExternalRef.source == SOURCE,
            CanonicalIngredientExternalRef.source_version == candidate.source_version,
            CanonicalIngredientExternalRef.external_id == candidate.food_code,
        )
    )
    if ref is None:
        ref = CanonicalIngredientExternalRef(
            source=SOURCE,
            source_version=candidate.source_version,
            external_id=candidate.food_code,
            canonical_ingredient_id=target_id,
        )
        session.add(ref)
    else:
        ref.canonical_ingredient_id = target_id
    ref.notes = rationale


def _load_candidate(
    session: Session, source_version: str, food_code: str
) -> CnfFoodCandidate:
    candidate = session.scalar(
        select(CnfFoodCandidate).where(
            CnfFoodCandidate.source_version == source_version,
            CnfFoodCandidate.food_code == food_code,
        )
    )
    if candidate is None:
        raise CandidateNotFound(
            f"Candidat FCÉN {source_version}/{food_code} introuvable."
        )
    return candidate


def _candidate_labels(candidate: CnfFoodCandidate) -> list[str]:
    return [
        label
        for label in (
            candidate.food_description_fr,
            candidate.food_description_en,
            candidate.alternate_description_fr,
            candidate.alternate_description_en,
        )
        if label
    ]


def _candidate_snapshot(candidate: CnfFoodCandidate) -> dict[str, Any]:
    return {
        "source_version": candidate.source_version,
        "archive_sha256": candidate.archive_sha256,
        "food_code": candidate.food_code,
        "food_description_fr": candidate.food_description_fr,
        "food_description_en": candidate.food_description_en,
        "alternate_description_fr": candidate.alternate_description_fr,
        "alternate_description_en": candidate.alternate_description_en,
        "cnf_food_group_code": candidate.cnf_food_group_code,
        "cnf_food_group_description_fr": (
            candidate.cnf_food_group_description_fr
        ),
    }


def _validate_decision(decision: CurationDecision) -> None:
    if not decision.reviewer.strip() or not decision.rationale.strip():
        raise CurationError("reviewer et rationale sont obligatoires.")
    if decision.action == IngredientCurationAction.attach_existing:
        if not decision.canonical_ingredient_id or decision.canonical is not None:
            raise CurationError(
                "attach_existing exige canonical_ingredient_id, sans canonical."
            )
    elif decision.action == IngredientCurationAction.create_variant:
        if decision.canonical is None or decision.canonical_ingredient_id is not None:
            raise CurationError(
                "create_variant exige canonical, sans canonical_ingredient_id."
            )
        spec = decision.canonical
        if not _SLUG.fullmatch(spec.id):
            raise CurationError(
                "canonical.id doit être un slug stable en minuscules."
            )
        expected_unit = {
            UnitKind.mass: "g",
            UnitKind.volume: "ml",
            UnitKind.count: "unit",
        }[spec.unit_kind]
        if spec.base_unit != expected_unit:
            raise CurationError(
                f"base_unit doit être '{expected_unit}' pour {spec.unit_kind.value}."
            )
        if spec.perishability is not None and not (
            Decimal("0") <= spec.perishability <= Decimal("1")
        ):
            raise CurationError("perishability doit être entre 0 et 1.")
        if (
            spec.salvage_value_cents_per_base_unit is not None
            and spec.salvage_value_cents_per_base_unit < 0
        ):
            raise CurationError(
                "salvage_value_cents_per_base_unit doit être positif ou nul."
            )
        if spec.density_g_per_ml is not None and spec.density_g_per_ml <= 0:
            raise CurationError("density_g_per_ml doit être strictement positive.")
    elif decision.canonical_ingredient_id is not None or decision.canonical is not None:
        raise CurationError("exclude ne doit pas désigner de cible canonique.")
    for alias in decision.aliases:
        if alias.language not in {"fr", "en"} or not normalize_label(alias.alias):
            raise CurationError("Chaque alias exige language=fr|en et un libellé.")
    if decision.action == IngredientCurationAction.exclude and decision.aliases:
        raise CurationError("exclude ne peut pas approuver d'alias.")


def decision_from_dict(raw: dict[str, Any]) -> CurationDecision:
    try:
        canonical_raw = raw.get("canonical")
        canonical = None
        if canonical_raw is not None:
            canonical = CanonicalSpec(
                id=str(canonical_raw["id"]),
                family_id=str(canonical_raw["family_id"]),
                name=str(canonical_raw["name"]),
                unit_kind=UnitKind(canonical_raw["unit_kind"]),
                base_unit=str(canonical_raw["base_unit"]),
                perishability=(
                    Decimal(str(canonical_raw["perishability"]))
                    if canonical_raw.get("perishability") is not None else None
                ),
                salvage_value_cents_per_base_unit=(
                    Decimal(str(canonical_raw["salvage_value_cents_per_base_unit"]))
                    if canonical_raw.get("salvage_value_cents_per_base_unit")
                    is not None else None
                ),
                density_g_per_ml=(
                    Decimal(str(canonical_raw["density_g_per_ml"]))
                    if canonical_raw.get("density_g_per_ml") is not None
                    else None
                ),
            )
        return CurationDecision(
            source_version=str(raw["source_version"]),
            food_code=str(raw["food_code"]),
            action=IngredientCurationAction(raw["action"]),
            reviewer=str(raw["reviewer"]),
            rationale=str(raw["rationale"]),
            canonical_ingredient_id=(
                str(raw["canonical_ingredient_id"])
                if raw.get("canonical_ingredient_id") is not None
                else None
            ),
            canonical=canonical,
            aliases=tuple(
                AliasSpec(language=str(alias["language"]), alias=str(alias["alias"]))
                for alias in raw.get("aliases", [])
            ),
            acknowledged_similar_ids=tuple(
                str(value) for value in raw.get("acknowledged_similar_ids", [])
            ),
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise CurationError(f"Décision de manifeste invalide : {exc}") from exc


def load_manifest(path: str | Path) -> tuple[CurationDecision, ...]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CurationError(f"Manifeste illisible : {exc}") from exc
    rows = raw.get("decisions") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise CurationError("Le manifeste doit être une liste ou contenir decisions.")
    return tuple(decision_from_dict(row) for row in rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preview = commands.add_parser("preview")
    preview.add_argument("--source-version", default="2026")
    preview.add_argument("--food-code", required=True)
    apply = commands.add_parser("apply")
    apply.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()

    with SessionLocal() as session:
        if args.command == "preview":
            result = preview_candidate(
                session, args.source_version, args.food_code
            )
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
            return
        decisions = load_manifest(args.manifest)
        results = [apply_decision(session, decision) for decision in decisions]
        session.commit()
    print(json.dumps([asdict(result) for result in results], indent=2))


if __name__ == "__main__":
    main()
