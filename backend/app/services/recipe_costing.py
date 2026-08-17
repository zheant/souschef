"""Calcul pur et explicable du prix d'une recette.

Ce module ne connaît ni SQLAlchemy ni HTTP. Les adaptateurs lui fournissent
des observations déjà normalisées; il agrège les ingrédients partageant un
même achat avant d'arrondir les formats.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import Iterable, Mapping, Sequence

from .supply_rules import SupplyRule, resolve_supply

__all__ = [
    "CostingOffer",
    "IngredientCostLine",
    "PurchaseCostLine",
    "RecipeCostingModule",
    "RecipeNotScalableError",
    "RecipeQuote",
    "SupplyRule",
]


class RecipeNotScalableError(ValueError):
    """La recette ne sait pas se chiffrer pour un autre nombre de portions.

    Une recette dont toutes les quantités vivent dans la composante fixe par lot
    décrit un lot, pas une portion. Les rescaler proportionnellement inventerait
    une donnée que la source ne publie pas; les ignorer en silence — ce que
    faisait le module — renvoyait le même panier sous un prix par portion faux.
    """

_CENT = Decimal("0.01")
_CONFIDENCE_RANK = {
    "exact": 0,
    "audited_conversion": 1,
    "estimated": 2,
    "incomplete": 3,
}


@dataclass(frozen=True)
class CostingOffer:
    product_external_key: str
    canonical_ingredient_id: str
    store_external_key: str
    quantity_in_base_unit: Decimal
    price_cents_cad: int
    tax_rate: Decimal = Decimal("0")
    regular_price_cents_cad: int | None = None
    is_promo: bool = False
    sale_mode: str = "fixed_package"
    purchase_increment_in_base_unit: Decimal | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    confidence: str = "exact"


@dataclass(frozen=True)
class IngredientCostLine:
    ingredient_id: str
    required_quantity: Decimal
    procurement_ingredient_id: str | None
    procurement_quantity: Decimal
    consumed_cost_cents: Decimal
    confidence: str
    resolution: str
    product_external_key: str | None = None
    store_external_key: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PurchaseCostLine:
    procurement_ingredient_id: str
    product_external_key: str
    store_external_key: str
    required_quantity: Decimal
    purchased_quantity: Decimal
    purchase_units: Decimal
    checkout_cost_cents: Decimal
    regular_cost_cents: Decimal
    surplus_quantity: Decimal
    confidence: str
    sale_mode: str


@dataclass(frozen=True)
class RecipeQuote:
    recipe_id: str
    recipe_name: str
    servings: int
    status: str
    consumed_cost_cents: Decimal | None
    consumed_cost_per_serving_cents: Decimal | None
    #: Ce que coûteraient les mêmes quantités au meilleur prix unitaire du
    #: marché, tous formats confondus. C'était la valeur principale; elle est
    #: 9,9 % sous le prix de tout panier réel, parce qu'elle valorise au format
    #: de gros ce que le panier achète au détail. Conservée à côté, jamais
    #: présentée comme le prix payé.
    best_unit_price_cents: Decimal | None
    autonomous_checkout_cents: Decimal | None
    regular_comparable_cents: Decimal | None
    promotional_savings_cents: Decimal | None
    #: Deux nombres de fiabilité différente, donc deux niveaux. L'ADR le dit :
    #: « le coût consommé reste calculable au prix unitaire, mais le
    #: décaissement autonome est signalé estimated ». Un niveau unique, pris au
    #: pire de toutes les lignes, faisait basculer un coût consommé exact parce
    #: qu'un produit se vendait au poids.
    consumed_confidence: str
    checkout_confidence: str
    #: `single_store` ou `multi_store`. Un décaissement autonome décrit une
    #: course; quand aucune bannière ne couvre tout, le devis le dit.
    basket_scope: str
    stores: tuple[str, ...]
    valid_from: str | None
    valid_to: str | None
    #: Renseignée quand aucune période commune n'existe; `None` sinon.
    validity_reason: str | None
    ingredients: tuple[IngredientCostLine, ...]
    purchases: tuple[PurchaseCostLine, ...]
    incomplete_ingredients: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


class RecipeCostingModule:
    @staticmethod
    def quote_all(
        recipes: Iterable[object],
        offers: Iterable[CostingOffer],
        servings: int | Mapping[str, int] | None = None,
        stores: Iterable[str] | None = None,
        supply_rules: Iterable[SupplyRule] = (),
        staples: Iterable[str] = (),
    ) -> list[RecipeQuote]:
        allowed_stores = set(stores) if stores is not None else None
        usable_offers = tuple(
            offer
            for offer in offers
            if allowed_stores is None or offer.store_external_key in allowed_stores
        )
        rules = {rule.ingredient_id: rule for rule in supply_rules}
        staple_ids = frozenset(staples)
        return [
            _quote_recipe(
                recipe,
                usable_offers,
                _servings_for(recipe, servings),
                rules,
                staple_ids,
            )
            for recipe in recipes
        ]


def _quote_recipe(
    recipe: object,
    offers: Sequence[CostingOffer],
    servings: int,
    rules: Mapping[str, SupplyRule],
    staples: frozenset[str] = frozenset(),
) -> RecipeQuote:
    recipe_id = str(_field(recipe, "id"))
    recipe_name = str(_field(recipe, "name"))
    requirements = _requirements(recipe, servings)
    resolutions: list[
        tuple[str, Decimal, str | None, Decimal, str, str, str | None]
    ] = []
    procurement_totals: dict[str, Decimal] = {}
    incomplete: list[str] = []

    for ingredient_id, required in requirements:
        supply = resolve_supply(ingredient_id, rules)
        if supply.kind == "essential":
            resolutions.append(
                (
                    ingredient_id,
                    required,
                    None,
                    Decimal("0"),
                    supply.confidence,
                    "essential",
                    supply.provenance,
                )
            )
            continue
        if supply.kind == "invalid_rule":
            incomplete.append(ingredient_id)
            resolutions.append(
                (
                    ingredient_id,
                    required,
                    None,
                    Decimal("0"),
                    "incomplete",
                    "invalid_rule",
                    supply.provenance,
                )
            )
            continue
        procurement_id = supply.procurement_ingredient_id
        procurement_qty = required * supply.factor
        confidence = supply.confidence
        resolution = supply.kind
        provenance = supply.provenance
        procurement_totals[procurement_id] = (
            procurement_totals.get(procurement_id, Decimal("0")) + procurement_qty
        )
        resolutions.append(
            (
                ingredient_id,
                required,
                procurement_id,
                procurement_qty,
                confidence,
                resolution,
                provenance,
            )
        )

    # Un décaissement autonome décrit une course, pas une tournée. Rien
    # n'imposait un magasin unique: une recette à deux ingrédients pouvait
    # ressortir avec deux bannières et un total qui suppose deux déplacements,
    # sans coût de transport ni signal, sous un libellé qui promet l'inverse.
    to_buy = {
        procurement_id: quantity
        for procurement_id, quantity in procurement_totals.items()
        if quantity > 0 and procurement_id not in staples
    }
    basket_store, basket_scope = _basket_store(offers, to_buy)

    selected: dict[str, tuple[CostingOffer, Decimal]] = {}
    best_unit_costs: dict[str, Decimal] = {}
    purchase_offers: list[CostingOffer] = []
    purchases: list[PurchaseCostLine] = []
    regular_totals: list[Decimal] = []
    for procurement_id, quantity in procurement_totals.items():
        if quantity <= 0:
            # Rien à chiffrer, donc rien à bloquer et rien à acheter. Une
            # exigence nulle produisait quand même une ligne d'achat à zéro
            # unité, et rendait le devis entier incomplet si l'ingrédient
            # n'avait aucun produit au marché.
            continue
        candidates = [
            offer
            for offer in offers
            if offer.canonical_ingredient_id == procurement_id
            and offer.quantity_in_base_unit > 0
            # Un prix nul n'est pas une preuve de gratuité, c'est une donnée
            # manquante. L'ADR l'interdit explicitement : « une donnée absente
            # rend le devis incomplet; elle ne devient jamais un coût nul ».
            # Seule une règle `essential` peut attribuer un coût nul.
            and offer.price_cents_cad > 0
        ]
        if not candidates:
            incomplete.extend(
                ingredient_id
                for ingredient_id, _required, parent, *_rest in resolutions
                if parent == procurement_id
            )
            continue
        if procurement_id in staples:
            # Un essentiel du ménage est consommé — donc valorisé — mais pas
            # racheté : le décaissement autonome facturait un sac de 1 kg pour
            # 1,25 g de sel, 800 fois le besoin, dans 27 recettes. Il reste
            # chiffrable, et reste bloquant si aucun produit ne le vend : le
            # mécanisme le rend non racheté, pas invisible. N'étant pas au
            # panier, il est valorisé au meilleur prix unitaire du marché.
            offer = min(candidates, key=_valuation_sort_key)
            selected[procurement_id] = (offer, _taxed_unit_price(offer))
            continue
        # Le format le moins cher à l'unité de mesure est presque toujours le
        # plus gros du magasin : acheter un sac de 50 lb pour 600 g de pommes de
        # terre n'est le panier de personne. Le panier prend donc le candidat
        # qui minimise la dépense réelle.
        in_scope = [
            candidate
            for candidate in candidates
            if basket_store is None or candidate.store_external_key == basket_store
        ] or candidates
        purchase_offer = min(
            in_scope,
            key=lambda candidate: (
                _checkout_cents(quantity, candidate),
                *_valuation_sort_key(candidate),
            ),
        )
        # ...et la valorisation suit ce produit-là. Elle prenait auparavant le
        # meilleur prix unitaire du magasin, tous formats confondus : 532 lignes
        # du rapport W33 étaient valorisées sur un produit autre que celui que
        # le panier achetait, et le coût consommé total sortait 9,9 % sous le
        # prix de n'importe quel panier réel — les pommes de terre valorisées au
        # sac de 50 lb pendant qu'on achète un sac de 3 lb. Le meilleur prix
        # unitaire reste publié à part (`best_unit_price_cents`) : il dit ce que
        # l'ingrédient vaut au mieux, sans prétendre être ce qu'on paie.
        selected[procurement_id] = (
            purchase_offer,
            _taxed_unit_price(purchase_offer),
        )
        best_unit_costs[procurement_id] = _taxed_unit_price(
            min(candidates, key=_valuation_sort_key)
        )
        purchase_offers.append(purchase_offer)
        purchase = _purchase_line(procurement_id, quantity, purchase_offer)
        purchases.append(purchase)
        # La référence « sans promotion » est le panier qu'on composerait
        # réellement aux prix réguliers — pas le prix régulier du panier
        # promotionnel. Quand la promo rend le gros format le moins cher, ces
        # deux nombres n'ont rien à voir : le second annonçait des économies de
        # 17,00 $ là où l'alternative réelle en coûte 1,00 $ de plus.
        #
        # Elle se compose dans le **même** magasin que le panier payé
        # (`in_scope`, pas `candidates`) : sinon on compare une course à une
        # tournée, et l'économie annoncée est celle d'un panier que personne ne
        # peut faire — systématiquement sous-estimée, puisque la référence
        # profite d'un magasin que le panier payé n'a pas le droit de visiter.
        regular_totals.append(
            min(
                _checkout_cents(quantity, candidate, _regular_price_cents(candidate))
                for candidate in in_scope
            )
        )

    ingredient_lines: list[IngredientCostLine] = []
    for (
        ingredient_id,
        required,
        procurement_id,
        procurement_qty,
        confidence,
        resolution,
        provenance,
    ) in resolutions:
        if procurement_id is None and resolution == "essential":
            ingredient_lines.append(
                IngredientCostLine(
                    ingredient_id,
                    required,
                    None,
                    Decimal("0"),
                    Decimal("0.00"),
                    confidence,
                    resolution,
                    reason=provenance,
                )
            )
            continue
        selection = selected.get(procurement_id or "")
        if selection is None and procurement_qty <= 0:
            ingredient_lines.append(
                IngredientCostLine(
                    ingredient_id,
                    required,
                    procurement_id,
                    procurement_qty,
                    Decimal("0.00"),
                    confidence,
                    resolution,
                    reason="no_quantity_required",
                )
            )
            continue
        if selection is None:
            ingredient_lines.append(
                IngredientCostLine(
                    ingredient_id,
                    required,
                    procurement_id,
                    procurement_qty,
                    Decimal("0.00"),
                    "incomplete",
                    resolution,
                    reason="no_priced_product",
                )
            )
            continue
        offer, unit_cost = selection
        line_confidence = _worst_confidence(confidence, offer.confidence)
        ingredient_lines.append(
            IngredientCostLine(
                ingredient_id,
                required,
                procurement_id,
                procurement_qty,
                _money(procurement_qty * unit_cost),
                line_confidence,
                resolution,
                offer.product_external_key,
                offer.store_external_key,
                provenance or ("household_staple" if procurement_id in staples else None),
            )
        )

    incomplete_ids = tuple(sorted(set(incomplete)))
    is_complete = not incomplete_ids
    # Chaque nombre n'agrège que ses propres composantes. Le coût consommé
    # valorise des quantités au prix unitaire et ne dépend pas de la façon dont
    # l'emballage s'achète; le décaissement, lui, en dépend entièrement.
    consumed_confidence = _worst_confidence(
        *(line.confidence for line in ingredient_lines)
    )
    checkout_confidence = _worst_confidence(
        consumed_confidence, *(line.confidence for line in purchases)
    )
    if not is_complete:
        consumed_confidence = checkout_confidence = "incomplete"
    consumed = (
        _money(sum((line.consumed_cost_cents for line in ingredient_lines), Decimal("0")))
        if is_complete
        else None
    )
    best_unit_price = (
        _money(
            sum(
                (
                    line.procurement_quantity
                    * best_unit_costs.get(
                        line.procurement_ingredient_id or "",
                        selected.get(line.procurement_ingredient_id or "", (None, Decimal("0")))[1],
                    )
                    for line in ingredient_lines
                    if line.procurement_ingredient_id is not None
                ),
                Decimal("0"),
            )
        )
        if is_complete
        else None
    )
    checkout = (
        _money(sum((line.checkout_cost_cents for line in purchases), Decimal("0")))
        if is_complete
        else None
    )
    regular = (
        _money(sum(regular_totals, Decimal("0"))) if is_complete else None
    )
    valid_from, valid_to, validity_reason = _validity_window(
        [offer for offer, _price in selected.values()] + purchase_offers
    )
    return RecipeQuote(
        recipe_id=recipe_id,
        recipe_name=recipe_name,
        servings=servings,
        status="complete" if is_complete else "incomplete",
        consumed_cost_cents=consumed,
        consumed_cost_per_serving_cents=(
            _money(consumed / servings) if consumed is not None else None
        ),
        best_unit_price_cents=best_unit_price,
        autonomous_checkout_cents=checkout,
        regular_comparable_cents=regular,
        promotional_savings_cents=(
            # Jamais négative : un prix régulier inférieur au prix courant est
            # une donnée fautive, pas une économie à rebours.
            _money(max(Decimal("0"), regular - checkout))
            if regular is not None and checkout is not None
            else None
        ),
        consumed_confidence=consumed_confidence,
        checkout_confidence=checkout_confidence,
        basket_scope=basket_scope,
        stores=tuple(sorted({line.store_external_key for line in purchases})),
        valid_from=valid_from,
        valid_to=valid_to,
        validity_reason=validity_reason,
        ingredients=tuple(ingredient_lines),
        purchases=tuple(purchases),
        incomplete_ingredients=incomplete_ids,
    )


def _requirements(recipe: object, servings: int) -> list[tuple[str, Decimal]]:
    result = []
    for row in _field(recipe, "ingredients"):
        ingredient_id = str(_field(row, "canonical_ingredient_id"))
        fixed = Decimal(str(_field(row, "qty_fixed_per_batch_base_unit")))
        marginal = Decimal(str(_field(row, "qty_marginal_per_serving_base_unit")))
        result.append((ingredient_id, max(Decimal("0"), fixed + marginal * servings)))
    return result


#: Modes de vente reconnus, énumérés ici et nulle part ailleurs. Une valeur
#: inconnue tombait auparavant dans la branche « au poids sans incrément », donc
#: « acheter exactement le besoin » : une faute de frappe en curation produisait
#: un décaissement plausible et faux, signalé seulement par une confiance
#: abaissée.
FIXED_PACKAGE = "fixed_package"
VARIABLE_WEIGHT = "variable_weight"
SALE_MODES = frozenset({FIXED_PACKAGE, VARIABLE_WEIGHT})

#: Pas minimal d'un achat au poids sans incrément publié, en fraction du format
#: de référence. 1 % d'un format de 1 kg vaut 10 g — une quantité qu'un comptoir
#: sait peser et qu'une caisse sait facturer.
WEIGHT_PURCHASE_STEP = Decimal("0.01")

#: Précision publiée des unités achetées. Sans elle, une division exacte sortait
#: en `0.006000006000006000006000006000` dans le rapport hebdomadaire.
_UNITS = Decimal("0.0001")


def _purchase_plan(quantity: Decimal, offer: CostingOffer) -> tuple[Decimal, Decimal, str]:
    """Unités achetées, quantité obtenue et confiance d'un achat réel."""
    if offer.sale_mode not in SALE_MODES:
        raise ValueError(
            f"Mode de vente inconnu: {offer.sale_mode!r} pour le produit "
            f"{offer.product_external_key!r}. Modes acceptés: "
            f"{', '.join(sorted(SALE_MODES))}."
        )
    reference = offer.quantity_in_base_unit
    confidence = offer.confidence
    if offer.sale_mode == FIXED_PACKAGE:
        purchase_units = (quantity / reference).to_integral_value(rounding=ROUND_CEILING)
        purchased = purchase_units * reference
    elif offer.purchase_increment_in_base_unit is not None:
        increment = Decimal(str(offer.purchase_increment_in_base_unit))
        steps = (quantity / increment).to_integral_value(rounding=ROUND_CEILING)
        purchased = steps * increment
        purchase_units = _ceil_to(purchased / reference, _UNITS)
    else:
        # Sans incrément publié, l'achat se faisait à la fraction exacte du
        # besoin — « acheter 0,003 kg d'ail », que personne ne pèse. Le pas
        # ci-dessous est relatif au format de référence, donc valable quelle que
        # soit son unité: 1 % d'un kilo, c'est 10 g.
        purchase_units = _ceil_to(quantity / reference, WEIGHT_PURCHASE_STEP)
        purchased = purchase_units * reference
        confidence = _worst_confidence(confidence, "estimated")
    return purchase_units, purchased, confidence


def _ceil_to(value: Decimal, step: Decimal) -> Decimal:
    """Arrondit vers le haut au multiple de ``step`` le plus proche."""
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def _checkout_cents(
    quantity: Decimal, offer: CostingOffer, price_cents: int | None = None
) -> Decimal:
    """Dépense réelle pour couvrir ``quantity`` avec cette offre.

    ``price_cents`` permet d'évaluer le même panier à un autre prix — le prix
    régulier — sans dupliquer l'arrondi des formats.
    """
    purchase_units, _purchased, _confidence = _purchase_plan(quantity, offer)
    unit_price = Decimal(offer.price_cents_cad if price_cents is None else price_cents)
    return _money(purchase_units * unit_price * (1 + offer.tax_rate))


def _regular_price_cents(offer: CostingOffer) -> int:
    """Prix hors promotion, ou le prix courant à défaut de référence publiée."""
    if offer.regular_price_cents_cad is None:
        return offer.price_cents_cad
    return max(offer.regular_price_cents_cad, offer.price_cents_cad)


def _purchase_line(
    procurement_id: str, quantity: Decimal, offer: CostingOffer
) -> PurchaseCostLine:
    purchase_units, purchased, confidence = _purchase_plan(quantity, offer)
    taxed_price = Decimal(offer.price_cents_cad) * (1 + offer.tax_rate)
    regular_price = Decimal(
        offer.regular_price_cents_cad
        if offer.regular_price_cents_cad is not None
        else offer.price_cents_cad
    ) * (1 + offer.tax_rate)
    return PurchaseCostLine(
        procurement_ingredient_id=procurement_id,
        product_external_key=offer.product_external_key,
        store_external_key=offer.store_external_key,
        required_quantity=quantity,
        purchased_quantity=purchased,
        purchase_units=purchase_units,
        checkout_cost_cents=_money(purchase_units * taxed_price),
        regular_cost_cents=_money(purchase_units * regular_price),
        surplus_quantity=purchased - quantity,
        confidence=confidence,
        sale_mode=offer.sale_mode,
    )


def _basket_store(
    offers: Sequence[CostingOffer], to_buy: Mapping[str, Decimal]
) -> tuple[str | None, str]:
    """Magasin où composer tout le panier, et la portée réellement obtenue.

    Rend ``(clé du magasin, "single_store")`` si une bannière couvre tous les
    ingrédients à acheter — la moins chère, à égalité la première par clé. Sinon
    ``(None, "multi_store")`` : le panier reste composé au meilleur prix partout,
    mais le devis le déclare au lieu de laisser croire à une seule course.
    """
    if not to_buy:
        return None, "single_store"
    stores = sorted({offer.store_external_key for offer in offers})
    priced: list[tuple[Decimal, str]] = []
    for store in stores:
        total = Decimal("0")
        for procurement_id, quantity in to_buy.items():
            candidates = [
                offer
                for offer in offers
                if offer.store_external_key == store
                and offer.canonical_ingredient_id == procurement_id
                and offer.quantity_in_base_unit > 0
                and offer.price_cents_cad > 0
            ]
            if not candidates:
                break
            total += min(_checkout_cents(quantity, offer) for offer in candidates)
        else:
            priced.append((total, store))
    if not priced:
        return None, "multi_store"
    return min(priced)[1], "single_store"


def _valuation_sort_key(offer: CostingOffer) -> tuple:
    """Ordre total sur les offres: prix unitaire, puis identité du produit.

    Le départage est explicite parce que `min` rend le premier minimum
    rencontré : deux formats au même prix unitaire faisaient dépendre le produit
    cité de l'ordre des offres, non garanti puisque la requête SQL n'ordonnait
    rien. L'ADR promet qu'on peut remonter d'un total vers un produit précis;
    une preuve qui change d'un appel à l'autre n'est pas une preuve.
    """
    return (
        _taxed_unit_price(offer),
        offer.store_external_key,
        offer.product_external_key,
    )


def _taxed_unit_price(offer: CostingOffer) -> Decimal:
    return (
        Decimal(offer.price_cents_cad)
        * (1 + offer.tax_rate)
        / offer.quantity_in_base_unit
    )


def _servings_for(recipe: object, servings: int | Mapping[str, int] | None) -> int:
    original = int(_field(recipe, "original_servings"))
    if servings is None:
        value = original
    elif isinstance(servings, Mapping):
        value = int(servings.get(str(_field(recipe, "id")), original))
    else:
        value = int(servings)
    if value <= 0:
        raise ValueError("Le nombre de portions doit être strictement positif.")
    if value != original and not _has_marginal_component(recipe):
        raise RecipeNotScalableError(
            f"La recette {str(_field(recipe, 'id'))!r} ne porte aucune quantité "
            f"marginale par portion: elle ne peut être chiffrée que pour son "
            f"rendement publié ({original} portions). Demander {value} portions "
            "renverrait la même nourriture et le même panier, avec un prix par "
            "portion faux."
        )
    return value


def _has_marginal_component(recipe: object) -> bool:
    return any(
        Decimal(str(_field(row, "qty_marginal_per_serving_base_unit"))) != 0
        for row in _field(recipe, "ingredients")
    )


def _field(value: object, name: str):
    return value[name] if isinstance(value, Mapping) else getattr(value, name)


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _worst_confidence(*values: str) -> str:
    if not values:
        return "exact"
    unknown = [value for value in values if value not in _CONFIDENCE_RANK]
    if unknown:
        raise ValueError(f"Niveau de confiance inconnu: {unknown[0]!r}")
    return max(values, key=_CONFIDENCE_RANK.__getitem__)


def _validity_window(
    offers: Sequence[CostingOffer],
) -> tuple[str | None, str | None, str | None]:
    """Période où toutes les offres retenues sont simultanément valides.

    Le plus tard des débuts et le plus tôt des fins ne décrivent une période que
    s'ils se croisent. Sur des offres aux fenêtres disjointes, la paire sortait
    à l'envers — « valide du 20 août au 19 août » — et était publiée telle
    quelle. Un devis ne prétend pas être valable sur une période impossible : il
    dit qu'il n'en a pas.
    """
    starts = [offer.valid_from for offer in offers if offer.valid_from]
    ends = [offer.valid_to for offer in offers if offer.valid_to]
    valid_from = max(starts) if starts else None
    valid_to = min(ends) if ends else None
    if valid_from is not None and valid_to is not None and valid_from > valid_to:
        return None, None, "no_common_validity_window"
    return valid_from, valid_to, None
