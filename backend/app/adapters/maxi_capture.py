"""Adaptateur des captures navigateur Maxi vers la structure Souschef.

Les captures restent des preuves immuables.  Cet adaptateur ne connaît aucun
ancien identifiant ``INGREDIENT_NNN`` : il charge les slugs et alias du
catalogue canonique Souschef, prépare les lignes ``market.product`` et expose
les prix par le ``CircularPort`` existant.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Mapping

from ..ingestion.ingredient_curation import normalize_label
from ..ports.dto import RawOfferDTO


_PACKAGE = re.compile(
    r"^\s*(?:(?P<count>\d+)\s*[x×]\s*)?"
    r"(?P<quantity>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>kg|g|mg|lb|lbs|oz|l|ml|ea|each|unit|units|un|ct|count)\b",
    re.IGNORECASE,
)
_UNIT_FACTORS = {
    "mg": (Decimal("0.001"), "g", "mass"),
    "g": (Decimal("1"), "g", "mass"),
    "kg": (Decimal("1000"), "g", "mass"),
    "lb": (Decimal("453.59237"), "g", "mass"),
    "lbs": (Decimal("453.59237"), "g", "mass"),
    "oz": (Decimal("28.349523125"), "g", "mass"),
    "ml": (Decimal("1"), "ml", "volume"),
    "l": (Decimal("1000"), "ml", "volume"),
    "ea": (Decimal("1"), "unit", "count"),
    "each": (Decimal("1"), "unit", "count"),
    "unit": (Decimal("1"), "unit", "count"),
    "units": (Decimal("1"), "unit", "count"),
    "un": (Decimal("1"), "unit", "count"),
    "ct": (Decimal("1"), "unit", "count"),
    "count": (Decimal("1"), "unit", "count"),
}

# Des qualificatifs qui ne changent pas l'identité alimentaire. Les états
# importants (surgelé, cuit, fumé, pané, etc.) sont volontairement absents.
_SAFE_TITLE_TOKENS = {
    "all", "assorted", "bag", "boneless", "canada", "canadian", "club",
    "extra", "free", "grade", "large", "lean", "medium", "mini", "no",
    "non", "organic", "pack", "raised", "range", "skinless", "small",
    "natural", "only", "peanuts", "smooth", "crunchy", "light",
    "size", "value", "white", "brown",
    "g", "kg", "lb", "lbs", "oz", "ml", "l", "ea", "ct", "x",
}


@dataclass(frozen=True)
class CanonicalEntry:
    id: str
    name: str
    unit_kind: str
    base_unit: str
    alias_tokens: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class ParsedPackage:
    quantity_in_base_unit: Decimal
    base_unit: str
    unit_kind: str
    display: str


@dataclass(frozen=True)
class ProductQuantityConversion:
    canonical_ingredient_id: str
    from_unit_kind: str
    from_base_unit: str
    canonical_units_per_source_unit: Decimal
    confidence: str
    provenance: str


@dataclass(frozen=True)
class MaxiMatchDecision:
    source_product_id: str
    product_name: str
    status: str
    canonical_ingredient_id: str | None
    candidate_ids: tuple[str, ...]
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class _PreparedProduct:
    product_row: dict
    offer: RawOfferDTO


@dataclass(frozen=True)
class IdentityRules:
    """Refuse qu'un produit composé tienne lieu d'ingrédient de base.

    « Bagels aux graines de sésame » n'est pas du sésame, « Craquelins au
    cheddar » n'est pas du cheddar, « Pains naan à l'ail » n'est pas de l'ail.
    Ces appariements ne faussaient rien tant qu'une garde de dimension les
    écartait par accident ; dès qu'une conversion existe, le produit composé
    devient achetable — et souvent le moins cher au 100 g, donc retenu.

    Le marqueur ne disqualifie que s'il est absent de l'identité du canonique
    lui-même : « Pain au levain » reste un pain, « Sauce BBQ » reste une sauce
    barbecue si l'alias le dit.
    """

    composed_markers: tuple[str, ...] = ()
    #: Marqueurs qui disqualifient un produit pour un ingrédient précis, là où
    #: le marqueur reste légitime ailleurs : un bouillon « sans gras » est un
    #: bouillon, un cheddar « sans gras » n'est pas du cheddar.
    ingredient_markers: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: Formats de gros. Question distincte de l'identité : « Demi caisse de
    #: figues fraîches » EST bien des figues, mais le format publié (« 1 ea »)
    #: ne dit pas combien elle en contient. L'équivalence à la pièce du
    #: canonique s'y appliquait quand même, ce qui valorisait la figue à
    #: 200 $/kg. Faute de quantité publiée, le produit n'est pas chiffrable.
    wholesale_markers: tuple[str, ...] = ()
    #: Rayons dont seuls quelques ingrédients peuvent légitimement provenir,
    #: sous la forme ``(fragment d'URL, ids autorisés, raison)``. Le rayon est
    #: la preuve du détaillant lui-même, bien plus solide qu'un mot du titre :
    #: une bière au miel rangée dans « bières et vins » ne peut pas fournir du
    #: miel, alors qu'une « Sauce barbecue avec bière Guinness » rangée dans les
    #: condiments reste une sauce barbecue, et « Vinaigre de vin blanc » un
    #: vinaigre. Un marqueur posé sur le titre rejetait ces deux-là.
    restricted_categories: tuple[tuple[str, frozenset[str], str], ...] = ()

    def restricted_category(
        self, category_url: str | None, canonical: CanonicalEntry
    ) -> str | None:
        haystack = (category_url or "").casefold()
        for fragment, allowed, reason in self.restricted_categories:
            if fragment in haystack and canonical.id not in allowed:
                return reason
        return None

    def composed_marker(self, product_name: str, canonical: CanonicalEntry) -> str | None:
        product = normalize_label(product_name)
        identity = " ".join(
            [normalize_label(canonical.name)]
            + [" ".join(tokens) for tokens in canonical.alias_tokens]
        )
        for marker in self.composed_markers:
            needle = normalize_label(marker)
            if _has_words(product, needle) and not _has_words(identity, needle):
                return marker
        for marker in self.ingredient_markers.get(canonical.id, ()):
            if _has_words(product, normalize_label(marker)):
                return marker
        return None

    def wholesale_marker(self, product_name: str) -> str | None:
        """Le titre annonce-t-il un format de gros à quantité non publiée ?

        Le marqueur le plus long gagne, pour que « demi caisse » soit rapporté
        plutôt que « caisse » — le rapport de curation doit nommer ce qu'on a
        réellement vu.
        """
        product = normalize_label(product_name)
        matches = [
            marker
            for marker in self.wholesale_markers
            if _has_words(product, normalize_label(marker))
        ]
        return max(matches, key=len) if matches else None


def load_identity_rules(path: str | Path | None) -> IdentityRules | None:
    """Charge ``{composed_product_markers, disqualifying_markers_by_ingredient,
    wholesale_format_markers}``."""
    if path is None:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return IdentityRules(
        composed_markers=tuple(payload.get("composed_product_markers", [])),
        ingredient_markers={
            str(key): tuple(values)
            for key, values in (
                payload.get("disqualifying_markers_by_ingredient") or {}
            ).items()
        },
        wholesale_markers=tuple(payload.get("wholesale_format_markers", [])),
        restricted_categories=tuple(
            (
                str(row["category_fragment"]).casefold(),
                frozenset(row.get("allowed_canonical_ingredient_ids", [])),
                str(row.get("reason", "rayon_reserve")),
            )
            for row in payload.get("restricted_categories", [])
        ),
    )


def _has_words(haystack: str, needle: str) -> bool:
    """Le marqueur apparaît-il comme mot entier (ou suite de mots) ?

    Le pluriel compte comme le même mot — « Bagels aux graines de sésame »
    doit tomber sous le marqueur « bagel ». Mais rien de plus : « gaufrettes »
    n'est pas « gaufre », et une correspondance par sous-chaîne rejetterait
    « Pêche beignet » ou « Bifteck sandwich », deux aliments légitimes.
    """
    if not needle:
        return False
    tokens = haystack.split()
    wanted = needle.split()
    span = len(wanted)
    return any(
        all(
            _same_word(token, target)
            for token, target in zip(tokens[index : index + span], wanted)
        )
        for index in range(len(tokens) - span + 1)
    )


def _same_word(token: str, target: str) -> bool:
    return token == target or token in {f"{target}s", f"{target}x"}


@dataclass(frozen=True)
class TaxSchedule:
    """Taux de taxe par rayon du détaillant.

    L'épicerie de base est détaxée au Québec, mais pas tout ce qu'un magasin
    d'alimentation vend. Un taux unique appliqué à l'ensemble du catalogue —
    surtout un taux nul par défaut — fait disparaître silencieusement la taxe
    sur le vin de cuisson ou la bière d'une pâte à frire.
    """

    default_rate: Decimal
    rules: tuple[tuple[str, Decimal], ...] = ()

    def rate_for(self, category_url: str | None) -> Decimal:
        haystack = (category_url or "").lower()
        for fragment, rate in self.rules:
            if fragment in haystack:
                return rate
        return self.default_rate


def load_tax_schedule(path: str | Path | None) -> TaxSchedule | None:
    """Charge un barème ``{default_rate, rules: [{category_fragment, rate}]}``."""
    if path is None:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return TaxSchedule(
        default_rate=Decimal(str(payload.get("default_rate", "0"))),
        rules=tuple(
            (str(row["category_fragment"]).lower(), Decimal(str(row["rate"])))
            for row in payload.get("rules", [])
        ),
    )


def load_match_overrides(path: str | Path | None) -> dict[str, str | None]:
    """Charge des décisions humaines ``produit Maxi -> slug Souschef``.

    Le fichier est une liste d'objets avec ``source_product_id``, ``status``
    (``approved`` ou ``rejected``) et, pour une approbation,
    ``canonical_ingredient_id``.
    """
    if path is None:
        return {}
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Le manifeste Maxi doit être une liste JSON.")
    result: dict[str, str | None] = {}
    for row in rows:
        source_id = str(row["source_product_id"])
        status = row["status"]
        if status == "approved":
            result[source_id] = str(row["canonical_ingredient_id"])
        elif status == "rejected":
            result[source_id] = None
        else:
            raise ValueError(f"Statut Maxi inconnu pour {source_id}: {status!r}")
    return result


def load_title_overrides(path: str | Path | None) -> dict[str, str | None]:
    """Charge les décisions durables fondées sur un titre commercial normalisé."""
    if path is None:
        return {}
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Le manifeste de titres Maxi doit être une liste JSON.")
    result: dict[str, str | None] = {}
    for row in rows:
        title = normalize_label(str(row["normalized_title"]))
        status = row["status"]
        if status == "approved":
            result[title] = str(row["canonical_ingredient_id"])
        elif status == "rejected":
            result[title] = None
        else:
            raise ValueError(f"Statut de titre Maxi inconnu pour {title}: {status!r}")
    return result


def load_product_conversions(
    path: str | Path | None,
) -> dict[str, tuple[ProductQuantityConversion, ...]]:
    if path is None:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("product_conversions", [])
    result: dict[str, list[ProductQuantityConversion]] = {}
    for row in rows:
        confidence = str(row["confidence"])
        if confidence not in {"audited_conversion", "estimated"}:
            raise ValueError(f"Confiance de conversion invalide: {confidence!r}")
        multiplier = Decimal(str(row["canonical_units_per_source_unit"]))
        if multiplier <= 0:
            raise ValueError("Une conversion produit doit être strictement positive.")
        conversion = ProductQuantityConversion(
            canonical_ingredient_id=str(row["canonical_ingredient_id"]),
            from_unit_kind=str(row["from_unit_kind"]),
            from_base_unit=str(row["from_base_unit"]),
            canonical_units_per_source_unit=multiplier,
            confidence=confidence,
            provenance=str(row["provenance"]),
        )
        result.setdefault(conversion.canonical_ingredient_id, []).append(conversion)
    return {key: tuple(value) for key, value in result.items()}


class MaxiCaptureAdapter:
    """Prépare une capture Maxi pour l'ingestion native de Souschef.

    Le magasin et les dates sont obligatoires : ils ne sont jamais déduits du
    ``defaultStoreId`` de Maxi ni inventés à partir de l'heure de capture.
    """

    def __init__(
        self,
        capture_dirs: Iterable[str | Path],
        canonical_seed_dir: str | Path,
        *,
        store_external_key: str,
        week: str,
        valid_from: date,
        valid_to: date,
        overrides: Mapping[str, str | None] | None = None,
        title_overrides: Mapping[str, str | None] | None = None,
        tax_rate: Decimal = Decimal("0"),
        tax_schedule: "TaxSchedule | None" = None,
        identity_rules: "IdentityRules | None" = None,
        source_name: str = "Maxi",
        source_prefix: str = "maxi",
        allowed_canonical_ids: set[str] | None = None,
        product_conversions: Mapping[
            str, tuple[ProductQuantityConversion, ...]
        ] | None = None,
    ):
        if not re.fullmatch(r"\d{4}-W\d{2}", week):
            raise ValueError("week doit respecter le format YYYY-Www.")
        if valid_to < valid_from:
            raise ValueError("valid_to doit être postérieur ou égal à valid_from.")
        if not store_external_key:
            raise ValueError("Un magasin Souschef explicite est obligatoire.")
        if not re.fullmatch(r"[a-z0-9_-]+", source_prefix):
            raise ValueError("source_prefix doit être un identifiant URL sûr.")

        self.store_external_key = store_external_key
        self.week = week
        self.source_name = source_name
        self.source_prefix = source_prefix
        self._catalogue = _load_catalogue(Path(canonical_seed_dir))
        self._allowed_canonical_ids = allowed_canonical_ids
        if allowed_canonical_ids is not None:
            unknown_allowed = sorted(allowed_canonical_ids - self._catalogue.keys())
            if unknown_allowed:
                raise ValueError(
                    f"Ingrédients autorisés inconnus pour {source_name}: {unknown_allowed}"
                )
        self._overrides = dict(overrides or {})
        self._identity_rules = identity_rules
        self._product_conversions = dict(product_conversions or {})
        self._title_overrides = {
            normalize_label(key): value for key, value in (title_overrides or {}).items()
        }
        unknown = sorted(
            {
                value
                for value in (*self._overrides.values(), *self._title_overrides.values())
                if value is not None
            }
            - self._catalogue.keys()
        )
        if unknown:
            raise ValueError(
                f"Slugs canoniques inconnus dans le manifeste {source_name}: {unknown}"
            )

        self._decisions: list[MaxiMatchDecision] = []
        self._prepared: list[_PreparedProduct] = []
        self._source_products = _load_capture_products(capture_dirs)
        for source_id, raw in sorted(self._source_products.items()):
            decision, prepared = self._prepare(
                source_id,
                raw,
                valid_from,
                valid_to,
                tax_schedule.rate_for(raw.get("category_url"))
                if tax_schedule is not None
                else tax_rate,
            )
            self._decisions.append(decision)
            if prepared is not None:
                self._prepared.append(prepared)

    @property
    def decisions(self) -> tuple[MaxiMatchDecision, ...]:
        return tuple(self._decisions)

    def product_rows(self) -> list[dict]:
        """Lignes prêtes pour un upsert de ``market.product``."""
        return [dict(item.product_row) for item in self._prepared]

    def source_products(self) -> dict[str, dict]:
        """Produits bruts dédupliqués, indexés par identité commerciale."""
        return {
            source_id: dict(raw)
            for source_id, raw in self._source_products.items()
        }

    def fetch_week(self, store_id: str, week: str) -> list[RawOfferDTO]:
        if store_id != self.store_external_key or week != self.week:
            return []
        return [item.offer for item in self._prepared]

    def all_store_keys(self) -> list[str]:
        return [self.store_external_key]

    def all_weeks(self) -> list[str]:
        return [self.week]

    def report(self) -> dict:
        counts: dict[str, int] = {}
        for decision in self._decisions:
            counts[decision.status] = counts.get(decision.status, 0) + 1
        covered = {
            decision.canonical_ingredient_id
            for decision in self._decisions
            if decision.status == "matched"
        }
        return {
            "source_products": len(self._decisions),
            "importable_products": len(self._prepared),
            "promotional_products": sum(
                1 for item in self._prepared if item.offer.is_promo
            ),
            "canonical_ingredients_covered": len(covered),
            "decision_counts": dict(sorted(counts.items())),
            "store_external_key": self.store_external_key,
            "week": self.week,
        }

    def _prepare(
        self,
        source_id: str,
        raw: dict,
        valid_from: date,
        valid_to: date,
        tax_rate: Decimal,
    ) -> tuple[MaxiMatchDecision, _PreparedProduct | None]:
        name = str(raw.get("name") or "").strip()
        if not name:
            return _decision(source_id, name, "rejected", reason="missing_name"), None

        sale_mode = str(raw.get("sale_mode") or "fixed_package")
        if sale_mode not in {"fixed_package", "variable_weight"}:
            return _decision(
                source_id, name, "review", reason="unknown_sale_mode"
            ), None
        canonical, candidates, match_reason = self._match(source_id, name)
        if canonical is None:
            status = "rejected" if match_reason == "human_rejected" else (
                "unmatched" if not candidates else "review"
            )
            return _decision(
                source_id, name, status, candidates=candidates, reason=match_reason
            ), None
        if self._identity_rules is not None:
            marker = self._identity_rules.composed_marker(name, canonical)
            if marker is not None:
                # La règle s'applique même à un appariement « approuvé » : les
                # approbations en lot (`existing_exact_match`) n'ont jamais été
                # relues une à une, et c'est exactement là que les produits
                # composés se sont glissés.
                return _decision(
                    source_id, name, "rejected", canonical=canonical.id,
                    candidates=(canonical.id,),
                    reason=f"produit_compose_{normalize_label(marker).replace(' ', '_')}",
                ), None
            restricted = self._identity_rules.restricted_category(
                raw.get("category_url"), canonical
            )
            if restricted is not None:
                return _decision(
                    source_id, name, "rejected", canonical=canonical.id,
                    candidates=(canonical.id,), reason=restricted,
                ), None
        if (
            self._allowed_canonical_ids is not None
            and canonical.id not in self._allowed_canonical_ids
        ):
            return _decision(
                source_id, name, "rejected", canonical=canonical.id,
                candidates=candidates or (canonical.id,),
                reason="not_used_in_recipes",
            ), None
        package = (
            _parse_unit_price_reference(raw)
            if sale_mode == "variable_weight"
            else _preferred_fixed_package(raw, canonical)
        )
        if package is None:
            return _decision(
                source_id, name, "review", canonical=canonical.id,
                candidates=(canonical.id,), reason="package_not_fixed_or_unparsed",
            ), None
        pricing_confidence = "exact"
        quantity_provenance = "Format publié par le détaillant"
        # Une conversion déclarée s'applique dès qu'elle correspond à la
        # dimension du format publié — y compris quand cette dimension est
        # déjà celle du canonique. L'ail en est le cas type : le détaillant
        # vend « 5 unités », le canonique se compte aussi en unités, mais une
        # unité vendue est un bulbe et l'unité de la recette est une gousse.
        # Ne chercher la règle que sur désaccord de dimension revenait à
        # facturer le bulbe entier au prix de la gousse.
        conversion = next(
            (
                item
                for item in self._product_conversions.get(canonical.id, ())
                if item.from_unit_kind == package.unit_kind
                and item.from_base_unit == package.base_unit
            ),
            None,
        )
        if conversion is None:
            if (
                package.unit_kind != canonical.unit_kind
                or package.base_unit != canonical.base_unit
            ):
                return _decision(
                    source_id, name, "review", canonical=canonical.id,
                    candidates=(canonical.id,), reason="package_dimension_incompatible",
                ), None
        else:
            # Un format de gros n'hérite pas d'une équivalence à la pièce.
            # « Demi caisse de figues fraîches », vendue « 1 ea », prenait
            # l'équivalence « 1 figue moyenne = 50 g » : la caisse entière était
            # facturée au poids d'une seule figue, soit 200 $/kg. Le titre
            # annonce un contenant, la quantité réelle n'est publiée nulle part.
            # La garde ne vise que ce cas : un format de gros qui publie une
            # vraie masse (« Caisse trio de tomates cerises, 680 g ») n'a besoin
            # d'aucune conversion et reste chiffrable.
            bulk = (
                self._identity_rules.wholesale_marker(name)
                if self._identity_rules is not None
                else None
            )
            if bulk is not None and conversion.from_unit_kind == "count":
                return _decision(
                    source_id, name, "review", canonical=canonical.id,
                    candidates=(canonical.id,),
                    reason="format_de_gros_quantite_non_publiee",
                ), None
            package = ParsedPackage(
                package.quantity_in_base_unit
                * conversion.canonical_units_per_source_unit,
                canonical.base_unit,
                canonical.unit_kind,
                package.display,
            )
            pricing_confidence = conversion.confidence
            quantity_provenance = conversion.provenance

        price = _money_cents(
            _variable_price(raw)
            if sale_mode == "variable_weight"
            else raw.get("displayed_sale_price") or raw.get("displayed_price")
        )
        if price is None or price <= 0:
            return _decision(
                source_id, name, "review", canonical=canonical.id,
                candidates=(canonical.id,), reason="missing_or_invalid_price",
            ), None
        regular_price = (
            None
            if sale_mode == "variable_weight"
            else _money_cents(raw.get("displayed_regular_price"))
        )
        is_promo = bool(raw.get("is_promo")) or (
            regular_price is not None and regular_price > price
        )
        external_key = _external_key(source_id, self.source_prefix)
        brand = str(raw.get("brand") or "Marque non indiquée").strip()
        raw_text = _raw_text(
            source_id, name, brand, package.display, self.source_prefix
        )

        product_row = {
            "external_key": external_key,
            "canonical_ingredient_id": canonical.id,
            "brand": brand,
            "package_qty_in_base_unit": package.quantity_in_base_unit,
            "package_unit": package.display,
            "sale_mode": sale_mode,
            "purchase_increment_in_base_unit": (
                _variable_purchase_increment(raw, package)
                if sale_mode == "variable_weight"
                else package.quantity_in_base_unit
            ),
            "quantity_confidence": pricing_confidence,
            "quantity_provenance": quantity_provenance,
            "tax_rate": tax_rate,
        }
        offer = RawOfferDTO(
            store_external_key=self.store_external_key,
            week=self.week,
            raw_text=raw_text,
            product_external_key=external_key,
            price_cents_cad=price,
            regular_price_cents_cad=regular_price,
            is_promo=is_promo,
            pricing_confidence=pricing_confidence,
            valid_from=valid_from.isoformat(),
            valid_to=valid_to.isoformat(),
        )
        return _decision(
            source_id, name, "matched", canonical=canonical.id,
            candidates=candidates or (canonical.id,), reason=match_reason,
        ), _PreparedProduct(product_row, offer)

    def _match(
        self, source_id: str, product_name: str
    ) -> tuple[CanonicalEntry | None, tuple[str, ...], str]:
        if source_id in self._overrides:
            canonical_id = self._overrides[source_id]
            if canonical_id is None:
                return None, (), "human_rejected"
            return self._catalogue[canonical_id], (canonical_id,), "human_approved"

        normalized_title = normalize_label(product_name)
        if normalized_title in self._title_overrides:
            canonical_id = self._title_overrides[normalized_title]
            if canonical_id is None:
                return None, (), "human_title_rejected"
            return self._catalogue[canonical_id], (canonical_id,), "human_title_approved"

        tokens = [token for token in normalize_label(product_name).split() if token != "size"]
        phrase_candidates: dict[str, tuple[int, bool]] = {}
        for canonical in self._catalogue.values():
            best: tuple[int, bool] | None = None
            for alias_tokens in canonical.alias_tokens:
                span = _find_phrase(tokens, alias_tokens)
                if span is None:
                    continue
                start, end = span
                remaining = tokens[:start] + tokens[end:]
                safe = all(_safe_title_token(token) for token in remaining)
                score = len(alias_tokens)
                if best is None or (safe, score) > (best[1], best[0]):
                    best = (score, safe)
            if best is not None:
                phrase_candidates[canonical.id] = best

        candidate_ids = tuple(sorted(phrase_candidates))
        safe = {
            canonical_id: score
            for canonical_id, (score, is_safe) in phrase_candidates.items()
            if is_safe
        }
        if not safe:
            reason = "no_canonical_alias" if not candidate_ids else "identity_requires_review"
            return None, candidate_ids, reason

        longest = max(safe.values())
        winners = sorted(cid for cid, score in safe.items() if score == longest)
        if len(winners) != 1:
            return None, candidate_ids, "ambiguous_canonical_identity"
        return self._catalogue[winners[0]], candidate_ids, "exact_canonical_alias"


def _load_catalogue(seed_dir: Path) -> dict[str, CanonicalEntry]:
    ingredients = json.loads(
        (seed_dir / "canonical_ingredients.json").read_text(encoding="utf-8")
    )
    aliases = json.loads(
        (seed_dir / "canonical_ingredient_aliases.json").read_text(encoding="utf-8")
    )
    aliases_by_id: dict[str, set[str]] = {}
    for row in aliases:
        aliases_by_id.setdefault(row["canonical_ingredient_id"], set()).add(
            row["alias"]
        )
    catalogue = {}
    for row in ingredients:
        names = aliases_by_id.get(row["id"], set()) | {row["name"]}
        catalogue[row["id"]] = CanonicalEntry(
            id=row["id"], name=row["name"], unit_kind=row["unit_kind"],
            base_unit=row["base_unit"],
            alias_tokens=tuple(
                sorted({tuple(normalize_label(name).split()) for name in names})
            ),
        )
    return catalogue


def _load_capture_products(
    capture_dirs: Iterable[str | Path],
) -> dict[str, dict]:
    observations: dict[str, list[tuple[datetime, dict]]] = {}
    for directory in sorted(Path(path) for path in capture_dirs):
        for path in sorted(directory.glob("*.json")):
            page = json.loads(path.read_text(encoding="utf-8"))
            captured_at = _timestamp(page.get("captured_at"))
            for raw in page.get("products", []):
                if not isinstance(raw, dict) or not raw.get("in_listing", True):
                    continue
                source_id = str(
                    raw.get("retailer_product_id")
                    or raw.get("upc")
                    or raw.get("product_url")
                    or ""
                ).strip()
                if not source_id:
                    continue
                observations.setdefault(source_id, []).append((captured_at, raw))
    return {
        source_id: _richest_observation(rows)
        for source_id, rows in observations.items()
    }


_ENRICHABLE_CAPTURE_FIELDS = (
    "upc",
    "name",
    "brand",
    "package_text",
    "unit_details_text",
    "sale_mode",
    "average_package_text",
    "purchase_increment",
    "price_variant_text",
    "displayed_unit_price",
    "unit_price_reference_quantity",
    "unit_price_reference_unit",
    "product_url",
    "category_url",
)


def _richest_observation(rows: list[tuple[datetime, dict]]) -> dict:
    """Préserve la preuve promotionnelle puis complète ses champs manquants."""
    promotional = [row for row in rows if row[1].get("is_promo")]
    candidates = promotional or rows
    _seen, selected = max(
        candidates,
        key=lambda row: (_observation_richness(row[1]), row[0]),
    )
    richest = max(rows, key=lambda row: (_observation_richness(row[1]), row[0]))[1]
    merged = dict(selected)
    for field in _ENRICHABLE_CAPTURE_FIELDS:
        if merged.get(field) in (None, "", []) and richest.get(field) not in (
            None,
            "",
            [],
        ):
            merged[field] = richest[field]
    return merged


def _observation_richness(raw: Mapping[str, object]) -> int:
    return sum(raw.get(field) not in (None, "", []) for field in _ENRICHABLE_CAPTURE_FIELDS)


def _timestamp(value: object) -> datetime:
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except ValueError:
        return datetime.min


def _parse_package(value: object) -> ParsedPackage | None:
    text = str(value or "").strip()
    if not text or text.startswith("$"):
        return None
    match = _PACKAGE.match(text)
    if match is None:
        return None
    count = Decimal(match.group("count") or "1")
    quantity = Decimal(match.group("quantity").replace(",", "."))
    unit = match.group("unit").casefold()
    factor, base_unit, unit_kind = _UNIT_FACTORS[unit]
    total = count * quantity * factor
    amount = _decimal_text(quantity)
    display = f"{amount} {unit}" if count == 1 else f"{int(count)} x {amount} {unit}"
    return ParsedPackage(total, base_unit, unit_kind, display)


def _multipack_units(value: object) -> ParsedPackage | None:
    """Un emballage « 6 x 116 g » publie aussi un compte : six articles.

    Le compte est une quantité publiée par le détaillant, pas une déduction :
    une recette qui demande deux pains à sous-marin peut donc être chiffrée
    sans jamais convertir des grammes en unités.
    """
    text = str(value or "").strip()
    if not text or text.startswith("$"):
        return None
    match = _PACKAGE.match(text)
    if match is None or not match.group("count"):
        return None
    if _UNIT_FACTORS[match.group("unit").casefold()][2] == "count":
        return None  # « 4 ea » est déjà un compte, lu par _parse_package
    count = Decimal(match.group("count"))
    return ParsedPackage(count, "unit", "count", f"{int(count)} un")


def _preferred_fixed_package(
    raw: Mapping[str, object], canonical: CanonicalEntry
) -> ParsedPackage | None:
    """Choisit la dimension publiée compatible, sans inventer de conversion.

    Un détaillant peut afficher simultanément ``8 un - 488 g``. La quantité
    à utiliser dépend alors de l'unité canonique de la recette.
    """
    primary = _parse_package(raw.get("package_text"))
    candidates = [primary] if primary is not None else []
    details = str(raw.get("unit_details_text") or "")
    for fragment in re.split(r"\s*[-–—]\s*", details):
        parsed = _parse_package(fragment)
        if parsed is not None and parsed not in candidates:
            candidates.append(parsed)
    for source in (raw.get("package_text"), details):
        multipack = _multipack_units(source)
        if multipack is not None and multipack not in candidates:
            candidates.append(multipack)
    single = _sold_as_single_unit(raw)
    if single is not None and single not in candidates:
        candidates.append(single)
    return next(
        (
            candidate
            for candidate in candidates
            if candidate.unit_kind == canonical.unit_kind
            and candidate.base_unit == canonical.base_unit
        ),
        primary or (candidates[0] if candidates else None),
    )


_COUNT_UNITS = frozenset({"ea", "each", "unit", "units", "un", "ct", "count"})


def _sold_as_single_unit(raw: Mapping[str, object]) -> ParsedPackage | None:
    """Reconnaît un format publié comme « une unité », sans masse annoncée.

    Une botte d'oignons verts ou un pied de céleri n'a pas de format en grammes
    chez le détaillant : le seul format publié est le prix unitaire, « 1,99 $ /
    1 un », rigoureusement égal au prix affiché. Ce n'est pas une estimation,
    c'est la quantité vendue telle que publiée.

    Toute autre référence (100 g, 1 kg) est un prix de comparaison et non un
    emballage : la retenir comme format ferait payer 100 g au prix du paquet.
    L'égalité des deux prix est donc exigée, pas seulement la présence d'une
    référence à l'unité.
    """
    unit = str(raw.get("unit_price_reference_unit") or "").casefold()
    quantity = str(raw.get("unit_price_reference_quantity") or "").strip()
    if unit not in _COUNT_UNITS:
        return None
    try:
        if Decimal(quantity.replace(",", ".")) != 1:
            return None
    except InvalidOperation:
        return None
    unit_price = _money_cents(raw.get("displayed_unit_price"))
    price = _money_cents(
        raw.get("displayed_sale_price") or raw.get("displayed_price")
    )
    if unit_price is None or price is None or unit_price != price:
        return None
    return ParsedPackage(Decimal("1"), "unit", "count", "1 un")


def _parse_unit_price_reference(raw: Mapping[str, object]) -> ParsedPackage | None:
    price = raw.get("displayed_unit_price")
    variant = _parse_package(raw.get("price_variant_text"))
    if _money_cents(raw.get("displayed_price")) is not None and variant is not None:
        return variant
    quantity = raw.get("unit_price_reference_quantity")
    unit = raw.get("unit_price_reference_unit")
    if _money_cents(price) is None or quantity in (None, "") or not unit:
        return None
    return _parse_package(f"{quantity} {unit}")


def _variable_price(raw: Mapping[str, object]) -> object:
    if _parse_package(raw.get("price_variant_text")) is not None:
        return raw.get("displayed_price")
    return raw.get("displayed_unit_price")


def _variable_purchase_increment(
    raw: Mapping[str, object], pricing_reference: ParsedPackage
) -> Decimal | None:
    """Lit uniquement un incrément dont l'unité est publiée explicitement."""
    increment = _parse_package(raw.get("price_variant_text"))
    if increment is None:
        return None
    if (
        increment.unit_kind != pricing_reference.unit_kind
        or increment.base_unit != pricing_reference.base_unit
    ):
        return None
    return increment.quantity_in_base_unit


def _find_phrase(tokens: list[str], phrase: list[str]) -> tuple[int, int] | None:
    if not phrase or len(phrase) > len(tokens):
        return None
    for start in range(len(tokens) - len(phrase) + 1):
        window = tokens[start:start + len(phrase)]
        if all(_same_word(actual, expected) for actual, expected in zip(window, phrase)):
            return start, start + len(phrase)
    return None


def _same_word(actual: str, expected: str) -> bool:
    return actual == expected or _singular_word(actual) == _singular_word(expected)


def _singular_word(value: str) -> str:
    if value.endswith("ies"):
        return value[:-3] + "y"
    if value.endswith("oes"):
        return value[:-2]
    if value.endswith("s") and not value.endswith("ss"):
        return value[:-1]
    return value


def _safe_title_token(token: str) -> bool:
    return token in _SAFE_TITLE_TOKENS or token.isdigit() or bool(
        re.fullmatch(r"\d+(?:\.\d+)?", token)
    )


def _money_cents(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value).replace("$", "").strip())
    except InvalidOperation:
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _external_key(source_id: str, source_prefix: str = "maxi") -> str:
    candidate = f"{source_prefix}:{source_id}"
    if len(candidate) <= 64 and re.fullmatch(r"[A-Za-z0-9:_.-]+", candidate):
        return candidate
    return f"{source_prefix}:sha256:{sha256(source_id.encode()).hexdigest()[:32]}"


def _raw_text(
    source_id: str,
    name: str,
    brand: str,
    package: str,
    source_prefix: str = "maxi",
) -> str:
    suffix = f" | {package} | {source_prefix}:{source_id}"
    prefix = f"{brand} | {name}"
    return prefix[: max(0, 255 - len(suffix))] + suffix


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _decision(
    source_id: str,
    name: str,
    status: str,
    *,
    canonical: str | None = None,
    candidates: tuple[str, ...] = (),
    reason: str,
) -> MaxiMatchDecision:
    return MaxiMatchDecision(
        source_product_id=source_id,
        product_name=name,
        status=status,
        canonical_ingredient_id=canonical,
        candidate_ids=tuple(sorted(set(candidates))),
        reason=reason,
    )
