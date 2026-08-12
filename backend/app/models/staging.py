"""Schéma ``staging`` — atterrissage des données brutes avant normalisation.

Même avec l'adaptateur JSON de la v1, les offres passent par ici : un
retraitement doit être rejouable sans reperdre les données, et c'est ce
cheminement qu'on garde tel quel quand le vrai scraper arrivera
(docs/spec.md, « Architecture en couches »).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Enum, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, utcnow
from .market import MappingStatus

SCHEMA = "staging"


class IngredientCandidateStatus(str, enum.Enum):
    candidate = "candidate"
    review = "review"
    excluded = "excluded"
    approved = "approved"
    rejected = "rejected"


class CnfFoodCandidate(TimestampMixin, Base):
    """Copie bilingue rejouable d'une ligne ``Food_Name.csv`` du FCÉN.

    Une ligne importée n'est jamais un ingrédient canonique par défaut. Le
    statut initial ne fait qu'orienter la curation; un rejeu met à jour la
    donnée source sans écraser le statut ou les informations de révision.
    """

    __tablename__ = "cnf_food_candidate"
    __table_args__ = (
        UniqueConstraint("source_version", "food_code"),
        Index("ix_cnf_food_candidate_status", "curation_status"),
        Index("ix_cnf_food_candidate_group", "cnf_food_group_code"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_version: Mapped[str] = mapped_column(String(32))
    archive_sha256: Mapped[str] = mapped_column(String(64))
    food_code: Mapped[str] = mapped_column(String(32))
    food_description_en: Mapped[str] = mapped_column(Text)
    food_description_fr: Mapped[str] = mapped_column(Text)
    alternate_description_en: Mapped[str | None] = mapped_column(Text)
    alternate_description_fr: Mapped[str | None] = mapped_column(Text)
    food_source_code: Mapped[str | None] = mapped_column(String(32))
    usda_ndb_code: Mapped[str | None] = mapped_column(String(32))
    cnf_food_group_code: Mapped[str] = mapped_column(String(16))
    cnf_food_group_description_en: Mapped[str] = mapped_column(Text)
    cnf_food_group_description_fr: Mapped[str] = mapped_column(Text)
    comment_en: Mapped[str | None] = mapped_column(Text)
    comment_fr: Mapped[str | None] = mapped_column(Text)
    scientific_name: Mapped[str | None] = mapped_column(Text)
    food_last_updated_date: Mapped[str | None] = mapped_column(String(32))
    raw_payload: Mapped[dict] = mapped_column(JSONB)
    curation_status: Mapped[IngredientCandidateStatus] = mapped_column(
        Enum(
            IngredientCandidateStatus,
            name="ingredient_candidate_status",
            schema=SCHEMA,
        ),
        default=IngredientCandidateStatus.candidate,
        server_default=IngredientCandidateStatus.candidate.value,
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None]


class RawOffer(Base):
    __tablename__ = "raw_offer"
    __table_args__ = (
        # Idempotence du rejeu : une même offre (magasin, semaine, empreinte)
        # n'est jamais dupliquée.
        UniqueConstraint("store_external_key", "week", "payload_fingerprint"),
        Index("ix_raw_offer_status", "mapping_status"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    #: Clé du magasin telle que vue par la source (pas une FK : la donnée est brute).
    store_external_key: Mapped[str] = mapped_column(String(64))
    #: Semaine de circulaire, format ISO "YYYY-Www".
    week: Mapped[str] = mapped_column(String(10))
    #: Payload brut intégral de l'offre, tel que reçu du port d'acquisition.
    payload: Mapped[dict] = mapped_column(JSONB)
    #: Empreinte stable du payload (sha256 hex) pour l'unicité au rejeu.
    payload_fingerprint: Mapped[str] = mapped_column(String(64))
    mapping_status: Mapped[MappingStatus] = mapped_column(
        Enum(MappingStatus, name="mapping_status", schema=SCHEMA),
        default=MappingStatus.unmapped,
    )
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow)
