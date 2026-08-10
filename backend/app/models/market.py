"""Schéma ``market`` — alimenté par la couche d'ingestion (jamais dans le
chemin d'une requête HTTP).

Clés : contrairement à ``catalog`` (entités curées, slugs stables en clé
primaire), ``market`` utilise des **clés de substitution entières**. Les
produits scrapés n'auront pas de slug stable : l'instabilité des identifiants
externes est absorbée par ``external_key`` (unique, cible du ``ON CONFLICT``
au seeding) et, pour le texte libre des circulaires, par ``product_mapping``.

L'historique de prix est conservé : sans lui, impossible de distinguer un vrai
rabais d'un prix régulier annoncé en gros caractères (docs/spec.md).
"""

from __future__ import annotations

import enum
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

SCHEMA = "market"
CATALOG = "catalog"


class Store(TimestampMixin, Base):
    __tablename__ = "store"
    __table_args__ = (
        UniqueConstraint("external_key"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    #: Identifiant stable côté source/seed ; cible du ON CONFLICT au seeding.
    external_key: Mapped[str] = mapped_column(String(64))
    banner: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(255))
    lat: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    lng: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    #: Deux bannières au même centre commercial partagent cet identifiant :
    #: le terme forfaitaire de déplacement du second arrêt tombe alors à 0,25 $.
    shopping_center_id: Mapped[str | None] = mapped_column(String(64))

    prices: Mapped[list["Price"]] = relationship(back_populates="store")


class Product(TimestampMixin, Base):
    __tablename__ = "product"
    __table_args__ = (
        UniqueConstraint("external_key"),
        CheckConstraint("package_qty_in_base_unit > 0", name="package_qty_positive"),
        CheckConstraint("tax_rate >= 0 AND tax_rate < 1", name="tax_rate_range"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    #: Identifiant stable côté source/seed ; cible du ON CONFLICT au seeding.
    external_key: Mapped[str] = mapped_column(String(64))
    canonical_ingredient_id: Mapped[str] = mapped_column(
        ForeignKey(f"{CATALOG}.canonical_ingredient.id")
    )
    brand: Mapped[str] = mapped_column(String(120))
    #: v_p — contenance du format, exprimée dans la base_unit de l'ingrédient
    #: canonique (g, ml ou unité) ; toute conversion en amont passe par la
    #: fonction unique de conversion d'unités.
    package_qty_in_base_unit: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    #: Libellé d'origine du format, à des fins d'affichage ("900 g", "2 L").
    package_unit: Mapped[str] = mapped_column(String(32))
    #: t_p — taux de taxe combiné applicable au produit (0 pour la plupart des
    #: aliments de base).
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 5))

    prices: Mapped[list["Price"]] = relationship(back_populates="product")


class Price(Base):
    __tablename__ = "price"
    __table_args__ = (
        # Historique conservé : une ligne par (produit, magasin, période).
        UniqueConstraint("product_id", "store_id", "valid_from"),
        Index("ix_price_validity", "store_id", "valid_from", "valid_to"),
        CheckConstraint("price_cents_cad >= 0", name="price_nonneg"),
        CheckConstraint(
            "regular_price_cents_cad IS NULL OR regular_price_cents_cad >= 0",
            name="regular_price_nonneg",
        ),
        CheckConstraint("valid_to >= valid_from", name="validity_ordered"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.product.id"))
    store_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.store.id"))
    #: c_ps — prix affiché, en cents CAD (jamais de flottant pour l'argent).
    price_cents_cad: Mapped[int]
    valid_from: Mapped[date]
    valid_to: Mapped[date]
    is_promo: Mapped[bool] = mapped_column(default=False)
    regular_price_cents_cad: Mapped[int | None]

    product: Mapped[Product] = relationship(back_populates="prices")
    store: Mapped[Store] = relationship(back_populates="prices")


class MappingStatus(str, enum.Enum):
    unmapped = "unmapped"
    auto = "auto"
    confirmed = "confirmed"
    rejected = "rejected"


class ProductMapping(TimestampMixin, Base):
    """Correspondance texte brut → ingrédient canonique.

    Semi-manuelle en production ; prévue dès maintenant (docs/spec.md). C'est
    cette table — pas une clé primaire en slug — qui absorbe l'instabilité des
    identifiants du monde extérieur.
    """

    __tablename__ = "product_mapping"
    __table_args__ = (
        UniqueConstraint("raw_text"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_01"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    raw_text: Mapped[str] = mapped_column(String(255))
    canonical_ingredient_id: Mapped[str | None] = mapped_column(
        ForeignKey(f"{CATALOG}.canonical_ingredient.id")
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    confirmed_by: Mapped[str | None] = mapped_column(String(120))
