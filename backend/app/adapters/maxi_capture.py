"""Adaptateur des captures navigateur Maxi vers la structure Souschef.

Les captures restent des preuves immuables.  Cet adaptateur ne connaît aucun
ancien identifiant ``INGREDIENT_NNN`` : il charge les slugs et alias du
catalogue canonique Souschef, prépare les lignes ``market.product`` et expose
les prix par le ``CircularPort`` existant.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
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
    r"(?P<unit>kg|g|mg|lb|lbs|oz|l|ml|ea|each|unit|units|ct|count)\b",
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
        tax_rate: Decimal = Decimal("0"),
    ):
        if not re.fullmatch(r"\d{4}-W\d{2}", week):
            raise ValueError("week doit respecter le format YYYY-Www.")
        if valid_to < valid_from:
            raise ValueError("valid_to doit être postérieur ou égal à valid_from.")
        if not store_external_key:
            raise ValueError("Un magasin Souschef explicite est obligatoire.")

        self.store_external_key = store_external_key
        self.week = week
        self._catalogue = _load_catalogue(Path(canonical_seed_dir))
        self._overrides = dict(overrides or {})
        unknown = sorted(
            {value for value in self._overrides.values() if value is not None}
            - self._catalogue.keys()
        )
        if unknown:
            raise ValueError(f"Slugs canoniques inconnus dans le manifeste: {unknown}")

        self._decisions: list[MaxiMatchDecision] = []
        self._prepared: list[_PreparedProduct] = []
        products = _load_capture_products(capture_dirs)
        for source_id, raw in sorted(products.items()):
            decision, prepared = self._prepare(
                source_id, raw, valid_from, valid_to, tax_rate
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

        package = _parse_package(raw.get("package_text"))
        canonical, candidates, match_reason = self._match(source_id, name)
        if canonical is None:
            status = "rejected" if match_reason == "human_rejected" else (
                "unmatched" if not candidates else "review"
            )
            return _decision(
                source_id, name, status, candidates=candidates, reason=match_reason
            ), None
        if package is None:
            return _decision(
                source_id, name, "review", canonical=canonical.id,
                candidates=(canonical.id,), reason="package_not_fixed_or_unparsed",
            ), None
        if package.unit_kind != canonical.unit_kind or package.base_unit != canonical.base_unit:
            return _decision(
                source_id, name, "review", canonical=canonical.id,
                candidates=(canonical.id,), reason="package_dimension_incompatible",
            ), None

        price = _money_cents(raw.get("displayed_sale_price") or raw.get("displayed_price"))
        if price is None or price <= 0:
            return _decision(
                source_id, name, "review", canonical=canonical.id,
                candidates=(canonical.id,), reason="missing_or_invalid_price",
            ), None
        regular_price = _money_cents(raw.get("displayed_regular_price"))
        is_promo = regular_price is not None and regular_price > price
        external_key = _external_key(source_id)
        brand = str(raw.get("brand") or "Marque non indiquée").strip()
        raw_text = _raw_text(source_id, name, brand, package.display)

        product_row = {
            "external_key": external_key,
            "canonical_ingredient_id": canonical.id,
            "brand": brand,
            "package_qty_in_base_unit": package.quantity_in_base_unit,
            "package_unit": package.display,
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
    products: dict[str, tuple[datetime, dict]] = {}
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
                previous = products.get(source_id)
                if previous is None or captured_at >= previous[0]:
                    products[source_id] = (captured_at, raw)
    return {source_id: raw for source_id, (_seen, raw) in products.items()}


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


def _external_key(source_id: str) -> str:
    candidate = f"maxi:{source_id}"
    if len(candidate) <= 64 and re.fullmatch(r"[A-Za-z0-9:_.-]+", candidate):
        return candidate
    return f"maxi:sha256:{sha256(source_id.encode()).hexdigest()[:32]}"


def _raw_text(source_id: str, name: str, brand: str, package: str) -> str:
    suffix = f" | {package} | maxi:{source_id}"
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
