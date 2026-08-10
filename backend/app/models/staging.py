"""Schéma ``staging`` — atterrissage des données brutes avant normalisation.

Même avec l'adaptateur JSON de la v1, les offres passent par ici : un
retraitement doit être rejouable sans reperdre les données, et c'est ce
cheminement qu'on garde tel quel quand le vrai scraper arrivera
(docs/spec.md, « Architecture en couches »).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Enum, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utcnow
from .market import MappingStatus

SCHEMA = "staging"


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
