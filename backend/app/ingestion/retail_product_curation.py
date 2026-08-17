"""Curation durable des produits commerciaux vers le canon culinaire."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher

from .ingredient_curation import normalize_label


_EXCLUDED_CATEGORY_PARTS = (
    "/boissons/",
    "/collations/",
    "/charcuteries-et-plats-prepares/",
    "/plats-cuisines/",
    "/repas-et-plats-d-accompagnement/",
    "/entrees-et-collations/",
    "/tourtieres",
    "/burgers-et-batonnets",
    "/burgers-boulettes-et-saucisses",
    "/frites-et-rondelles-d-oignons",
    "/galettes-de-pommes-de-terre-et-rissolees",
    "/pommes-de-terre-rissolees",
    "/fromages-effilochables-et-collations",
    "/yogourts-a-boire",
    "/laits-aromatises",
    "/substituts-de-repas",
    "/diners-en-conserve",
    "/plats-d-acccompagnements/",
    "/ensembles-melanges-et-garnitures",
    "/decorations-et-glacages",
    "/aliments-en-conserve-et-en-pot/soupes",
    "/aliments-en-conserve-et-en-pot/viandes",
    "/aliments-en-conserve-et-en-pot/fruits",
    "/melanges-de-fines-herbes-et-d-epices",
    "/sauces-et-assaisonnements-en-sachet",
    "/sauces-de-cuisson",
    "/marinades-et-pates-de-cuisson",
    "/condiments-et-garnitures/vinaigrettes",
    "/assaisonnes-et-panes",
    "/amuse-gueules-et-hors-d-oeuvre",
)
_PREPARED_NAME = re.compile(
    r"\b(?:pr[eê]t(?:e|es|s)?[- ]?[àa] (?:manger|servir|cuire)|"
    r"instantan[eé](?:e|es|s)?|repas|pizza|tourt(?:e|i[eè]re)|"
    r"macaroni au fromage|burger|boulette|saucisse|croquette|"
    r"b[aâ]tonnet|pan[eé](?:e|es|s)?|farci(?:e|es|s)?|"
    r"marin[eé](?:e|es|s)?|assaisonn[eé](?:e|es|s)?|"
    r"saveur de|soupe|potage|gla[cç]age|rehausseur de caf[eé]|"
    r"colorant [àa] caf[eé]|hummus|trempette|poutine|quiche|"
    r"m[eé]lange [àa] (?:g[aâ]teau|muffins?|cr[eê]pes?|sauce)|"
    r"nouilles? .*assaisonnement|produit de fromage fondu|fondue |"
    r"tartinade de fromage|fromage [àa] tartiner|fromage .*\b(?:aux?|avec)\b|"
    r"yogourts? (?!.*\bnature\b).*(?:aux?|[àa] la|[àa] saveur|assorti|duo)|"
    r"(?:bavette|bifteck|c[oô]telette|poitrine|cuisse|aile|pilon|filet|"
    r"lani[eè]re|crevette|poisson) .*(?:bbq|barbecue|portugais|piri|"
    r"souvlaki|shish|miel|[eé]rable|chipotle|chimichurri|steakhouse|"
    r"trois poivres|buffalo)|m[eé]lange de (?:fruits|l[eé]gumes|fromages|"
    r"haricots|la mer|fruits de mer)|mac[eé]doine|assortiment de|"
    r"f[eè]ves au lard|f[eè]ves? (?:au|[àa] la|[àa] l)|"
    r"sauce (?:bolognaise|ros[eé]e|alfredo|hamburger|[àa] sandwich|"
    r"[àa] la king|pour (?:p[aâ]tes?|saut[eé]|cuisson))|"
    r"bouillon (?:tom yum|pho)|boudin|confit de canard|"
    r"effiloch[eé] de|cro[uû]te [àa] tarte|m[eé]lange [àa] farce)\b"
)
_COMPOSITE_OR_FLAVOURED_NAME = re.compile(
    r"\b(?:m[eé]lange d [eé]pices|herbes de provence|[eé]pices [àa] (?:poulet|"
    r"hamburger|bbq)|assaisonnement (?:italien|[àa] bagel)|"
    r"thon .*\b(?:au|aux)\b|sardines? .*(?:piment|kipper|fum[eé])|"
    r"hu[iî]tres? fum[eé]es?|sauce (?:au|aux|pour|tha[iï]e|orientale)|"
    r"pesto aux tomates|mini ravioli|mac and cheese|"
    r"boisson .*(?:chocolat|vanille|fraise|pois)|"
    r"yogourts? .*(?:bleuet|fraise|banane|citron|lime)|"
    r"(?:cari|tartare) .*poisson|poissons? en p[aâ]te|filets? de poisson en p[aâ]te|"
    r"pommes? de terre .*assaisonnement|m[eé]lange d assaisonnement|"
    r"p[aâ]te d [eé]pices|fraises? et (?:rhubarbe|bananes)|"
    r"m[eé]lange (?:tropical|de baies|de petits fruits)|"
    r"fromages? .*\b(?:espresso|jalapeno)\b)\b"
)
_REVIEWED_OUT_OF_SCOPE = re.compile(
    r"\b(?:gelee en poudre|poudings? au tapioca|m[eé]lange de (?:six|6|quatre|"
    r"4|3) (?:haricots|fromages)|haricots? (?:m[eé]lang[eé]s|saut[eé]s)|"
    r"sauce (?:tomate .*epices|[àa] l ail|[àa] la viande|bolognese)|"
    r"pesto classique .*romano|cr[eè]me de coco sucr[eé]e|"
    r"concentr[eé]e? de cr[eè]me sucr[eé]e|cannelloni au fromage|"
    r"p[aâ]tes [àa] lasagne aux epinards|boisson .*chocolat|"
    r"chaudr[eé]e|tartare|c[oô]telettes? d agneau .*(?:merguez|mediterrane)|"
    r"bavette de boeuf .*vin|tournedos .*bard[eé]s|"
    r"burgers? .*surgel[eé]s?|riz .*saveur|nouilles? au boeuf|"
    r"duo de porc et boeuf|roul[eé] de porc en saumure|cuisses? de canard confites?|"
    r"m[eé]lange pour p[aâ]te [àa] tempura|sauce tomate style italien|"
    r"cr[eè]me [àa] caf[eé] au moka|cr[eé]mette [àa] caf[eé]|"
    r"c[eé]r[eé]ales? de bl[eé] souffl[eé]|m[eé]lange d assaisonnements?|"
    r"brisures? de caramel au beurre|fromages? cheddar .*mozzarella|"
    r"[eé]pices? [àa] steak de l ouest|[eé]pices? bbq|"
    r"pointes? de steak .*plantes|culture de yogourt|"
    r"m[eé]lange printanier|feuilles? de laitues? croquantes|"
    r"duo de laitues?|biscuits?|macaroni .*fromage|"
    r"poulet en crapaudine .*bbq|^marinade|riz .*\b(?:aromatise|saveur)\b|"
    r"(?:saumon|moules?|sardines?) fum[eé](?:e|es|s)?|"
    r"c[oô]tes? de dos de porc .*bbq|ailes? de poulet .*poivre|"
    r"m[eé]lange de f[eè]ves .*pois chiches|cannelle sucr[eé]e)\b"
)
_GENERIC_INDEX_SNACK_OR_PREPARED = re.compile(
    r"\b(?:croustilles?|craquelins?|biscuits?|bonbons?|friandises?|gomme|"
    r"bretzels?|grignotines?|collations?|barres? (?:tendres?|de chocolat|"
    r"granola|proteinees?)|popcorn|creme glacee?|desserts? glaces?|"
    r"poudings?|gateaux?|tartes?|beignes?|gaufres?|crepes?|cereales?|"
    r"granola|muffins?|pains?|baguettes?|bagels?|naans?|croissants?|"
    r"saucisses?|hot[ -]?dogs?|pepperoni|bologne|salami|bacon|jambon|"
    r"burgers?|frites?|croquettes?|pizza|repas|plats? d accompagnement|"
    r"salade (?:hachee|preparee)|vinaigrettes?|trousse collation|"
    r"fromage fondu|batonnets? de fromage|guimauves?|confiserie|gelifies?|"
    r"cheezit|goldfish|pocky|kitkat|cornets?|pops? glaces?|parfaits? au chocolat|"
    r"chocolats? .*partage|tablettes? de chocolat|rouleaux? de printemps|"
    r"ramen|nouilles? au poulet|lasagnes? a la viande|ravioli boeuf|"
    r"cigares? au chou|tacos? (?:souples?|rigides?)|trousse a tacos|"
    r"souvlaki|cotes? levees? barbeque|chili avec haricots|"
    r"salades? (?:de pommes? de terre|de pates|de chou)|vol au vent|"
    r"galettes? de pommes? de terre|bouchees? de pommes? de terre|"
    r"cretons?|pepperettes?|saucisson|tartinade caramel|sirop grenadine|"
    r"haricots? .*porc|pois .*le sieur|miche .*tranche|ciabatta|sous marins?)\b"
)
_GENERIC_INDEX_DRINK = re.compile(
    r"\b(?:jus|nectar|limonade|cola|pepsi|coca cola|eau (?:petillante|"
    r"gazeuse|de source)|the glace|cafe (?:instantane|moulu|torr[eé]fie)|"
    r"boisson (?:gazeuse|sportive|energisante|punch|aux? fruits?|aux? raisins?|"
    r"a l orange)|aromatisant d eau|lait frappe|lait au chocolat)\b"
)
_MARKETING_TOKENS = frozenset(
    {
        "biologique", "biologiques", "bio", "organic", "sac", "panier",
        "chopine", "paquet", "format", "selection", "sans", "leger",
        "legere", "legers", "legeres", "naturel", "naturelle", "naturels",
        "naturelles", "frais", "fraiche", "fraiches", "extra", "gros",
        "grosses", "petit", "petite", "petits", "petites",
    }
)


@dataclass(frozen=True)
class ProductCurationDecision:
    source_product_id: str
    product_name: str
    action: str
    canonical_ingredient_id: str | None
    reason: str
    confidence: str
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        row = asdict(self)
        row["evidence"] = list(self.evidence)
        return row


@dataclass(frozen=True)
class _Canonical:
    id: str
    name: str
    family_id: str
    labels: tuple[str, ...]


class CanonicalIndex:
    def __init__(self, entries: dict[str, _Canonical]):
        self.entries = entries
        self._token_to_ids: dict[str, set[str]] = {}
        for entry in entries.values():
            for label in entry.labels:
                for token in _reduced_tokens(label):
                    self._token_to_ids.setdefault(token, set()).add(entry.id)

    @classmethod
    def from_rows(cls, ingredients: list[dict], aliases: list[dict]):
        aliases_by_id: dict[str, set[str]] = {}
        for row in aliases:
            aliases_by_id.setdefault(row["canonical_ingredient_id"], set()).add(
                row["alias"]
            )
        return cls(
            {
                row["id"]: _Canonical(
                    id=row["id"],
                    name=row["name"],
                    family_id=row["family_id"],
                    labels=tuple(
                        sorted(
                            {
                                normalize_label(row["name"]),
                                *(
                                    normalize_label(value)
                                    for value in aliases_by_id.get(row["id"], set())
                                ),
                            }
                        )
                    ),
                )
                for row in ingredients
            }
        )

    def best_match(
        self,
        product_name: str,
        *,
        candidate_ids: list[str] | tuple[str, ...] | None = None,
        allowed_families: set[str] | None = None,
    ) -> tuple[_Canonical | None, float, float]:
        wanted = set(candidate_ids or ())
        if not wanted:
            # Un rapprochement global n'a aucune raison de comparer un produit
            # aux mille ingrédients du canon. Les candidats partageant au moins
            # un mot utile forment un rappel large et rendent la passe complète
            # suffisamment rapide pour être rejouée chaque semaine.
            for token in _reduced_tokens(normalize_label(product_name)):
                wanted.update(self._token_to_ids.get(token, ()))
            if not wanted:
                return None, 0.0, 0.0
        entries = [
            entry
            for entry in self.entries.values()
            if entry.id in wanted
            and (allowed_families is None or entry.family_id in allowed_families)
        ]
        scored = sorted(
            (
                (_entry_score(product_name, entry), entry)
                for entry in entries
            ),
            key=lambda item: (item[0], item[1].id),
            reverse=True,
        )
        if not scored:
            return None, 0.0, 0.0
        best_score, best = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        return best, best_score, second


def classify_product(
    product: dict,
    canonical: CanonicalIndex,
) -> ProductCurationDecision:
    source_id = str(product["source_product_id"])
    name = str(product.get("name") or "").strip()
    category = str(product.get("category_url") or "").casefold()
    normalized_name = normalize_label(name)
    if re.search(r"\byogourt .*base de noix de coco\b", normalized_name):
        return ProductCurationDecision(
            source_id, name, "canonical_gap", None,
            "distinct_ingredient_identity_missing_from_canonical_catalog",
            "high", (),
        )

    identity_override = _identity_override(normalized_name)
    if identity_override in canonical.entries:
        return ProductCurationDecision(
            source_id, name, "link_existing", identity_override,
            "curated_identity_override", "high",
            (canonical.entries[identity_override].name,),
        )

    existing_id = product.get("canonical_ingredient_id")
    if existing_id in canonical.entries:
        return ProductCurationDecision(
            source_id, name, "link_existing", existing_id,
            "existing_exact_match", "high", (str(existing_id),),
        )

    exact_candidates = [
        canonical.entries[value]
        for value in product.get("candidate_ids", [])
        if value in canonical.entries
        and normalized_name in canonical.entries[value].labels
    ]
    if len(exact_candidates) == 1:
        selected = exact_candidates[0]
        return ProductCurationDecision(
            source_id, name, "link_existing", selected.id,
            "exact_canonical_label_in_mixed_category", "high",
            (selected.name,),
        )

    name_excluded = _exclusion_reason(name, "")
    if name_excluded is not None:
        return ProductCurationDecision(
            source_id, name, "exclude", None, name_excluded, "high",
            (category,),
        )

    category_excluded = _exclusion_reason("", category)
    if category_excluded is not None:
        return ProductCurationDecision(
            source_id, name, "exclude", None, category_excluded, "high",
            (category,),
        )

    allowed_families = _families_for_category(category)
    candidate_ids = [
        value for value in product.get("candidate_ids", [])
        if value in canonical.entries
        and (
            allowed_families is None
            or canonical.entries[value].family_id in allowed_families
        )
    ]
    if len(candidate_ids) == 1:
        selected = canonical.entries[candidate_ids[0]]
        return ProductCurationDecision(
            source_id, name, "link_existing", selected.id,
            "single_compatible_canonical_candidate", "high", (selected.name,),
        )
    if candidate_ids:
        selected, score, second = canonical.best_match(
            name,
            candidate_ids=candidate_ids,
            allowed_families=allowed_families,
        )
        if selected is not None and score >= 0.52 and score - second >= 0.02:
            return ProductCurationDecision(
                source_id, name, "link_existing", selected.id,
                "best_compatible_canonical_candidate", "medium",
                (selected.name, f"score={score:.3f}", f"margin={score-second:.3f}"),
            )

    curated_id, curated_reason = _curated_identity(name, category)
    if curated_id in canonical.entries:
        return ProductCurationDecision(
            source_id, name, "link_existing", curated_id, curated_reason,
            "high", (canonical.entries[curated_id].name,),
        )

    selected, score, second = canonical.best_match(
        name, allowed_families=allowed_families
    )
    if selected is not None and score >= 0.82 and score - second >= 0.06:
        return ProductCurationDecision(
            source_id, name, "link_existing", selected.id,
            "strong_canonical_label_match", "medium",
            (selected.name, f"score={score:.3f}", f"margin={score-second:.3f}"),
        )
    return ProductCurationDecision(
        source_id, name, "canonical_gap", None,
        "no_supported_canonical_identity", "low",
        tuple(product.get("candidate_ids", [])),
    )


def _exclusion_reason(name: str, category: str) -> str | None:
    if any(part in category for part in _EXCLUDED_CATEGORY_PARTS):
        return "category_outside_culinary_ingredient_scope"
    normalized = normalize_label(name)
    if "/maxi/alimentation/" in category:
        plant_drink = bool(
            re.search(r"\bboisson .*(?:amande|avoine|soya|noix de coco)\b", normalized)
        )
        generic_drink = bool(
            _GENERIC_INDEX_DRINK.search(normalized)
            or ("boisson" in normalized and not plant_drink)
            or re.search(
                r"\b(?:soda|racinette|root beer|energy drink|sports? drink|"
                r"cocktail (?:de|aux)|eau minerale|eau de coco|cannette)\b",
                normalized,
            )
            or re.search(
                r"\b(?:cafe|biere|coke|clamato|fruit juice|d orange sans pulpe|"
                r"eau traitee|cocktail d orange)\b",
                normalized,
            )
        )
        non_food = bool(
            re.search(
                r"\b(?:papier hygienique|mouchoirs?|savon a vaisselle|eau de javel|"
                r"sac epicerie|fleur annuelle|cle panier)\b",
                normalized,
            )
        )
        flavoured_yogurt = "yogourt" in normalized and bool(
            re.search(r"\b(?:vanille|chocolat|tropical|arome|saveur)\b", normalized)
        ) and "nature" not in normalized
        indexed_processed = bool(
            re.search(
                r"\b(?:mirepoix|sauce (?:panda|pour saute|de cuisson)|esta sauce|"
                r"fromage .*twists|chips tortilla|melange .*chocolat|arachides? roties? au miel|"
                r"fromage .*mega bites|haricots? .*mexicaine|oeuf en chocolat|"
                r"pad thai|aerosol de cuisson|concentre congele de limade|"
                r"barre (?:truffle|choc)|burnt almond|bistro au levain|"
                r"torsades? reglisse|ragout boulettes|tartinade (?:originale|calorie wise)|"
                r"mini guacamole|croquilles|poulet miel et ail|the vert infuse|"
                r"ensemble de condiments|sauce hoisin|sauce de cuisson|taka ?tak|"
                r"assaisonnement pour tacos|season up|bhujia sev|roule suisse|"
                r"ailes? de poulet epicees?|bouchees? de poitrine de poulet|"
                r"lait glace|muesli|shreddies|lolly aux fruits|chocolats? europeens|"
                r"barres? rice krispies|barres? gout original|mini galettes|"
                r"tartelettes?|drumstick|coffee crisp|nouilles? masala|"
                r"nouilles? a la japonaise|noix de cajou roties? avec sel|"
                r"graines? de tournesol a saveur|fromage .*original.*tranches|"
                r"tranches? de fromage (?:epaisses? )?original|lotus biscoff|"
                r"chocolat noir et noix|fromage .*twists|fruit juice|"
                r"chips tortilla|caramel tartinade|cerises? au marasquin|"
                r"melange de barres|crisps? legume|porc miel et ail|"
                r"pommes? de terre rissolees?|nouilles? a la japonaise|"
                r"traditionnel a tartiner|tomates? ail huile olive|"
                r"barre chocolat au lait|ensemble pour lasagne|sirop original)\b",
                normalized,
            )
        )
        insufficient_identity = normalized in {
            "original", "fruits", "non aromatisee", "piquant", "zero bouteille",
            "zero sucre", "zero orange", "melange terre basse", "mirabel duo fleur de mirabel",
        }
        indexed_processed = indexed_processed or bool(
            re.search(
                r"\b(?:proteine non sucree vanille|sauce pout saute teriyaki|"
                r"amooza|chunky bouef|salade sud ouest|nouilles? a la japonaise|"
                r"rice krispies .*barres|huitres? .*fumees?)\b",
                normalized,
            )
        )
        indexed_processed = indexed_processed or bool(
            re.search(r"\bkefir .*vanille\b|\bnnouilles? a la japonaise\b", normalized)
        )
        indexed_processed = indexed_processed or bool(
            re.search(
                r"^barres?\b|\bsalade de (?!romaine)|\bmrbeast chocolat|"
                r"\btartinade au chocolat|\bcreme de framboise a la vanille\b",
                normalized,
            )
        )
        indexed_processed = indexed_processed or bool(
            re.search(
                r"\b(?:poitrine de dinde (?:fumee|rotie)|steaks? de .*style sud ouest|"
                r"fromage a la creme herbes|melange de fraises|sauce cremeuse|"
                r"roules? aux fruits|sauce a bifteck|fromage cheddar fume|"
                r"mais souffle|sardines? .*sauce .*chili|tomates? .*des .*epices|"
                r"creme de champignons condensee)\b",
                normalized,
            )
        )
        indexed_processed = indexed_processed or bool(
            re.search(
                r"\b(?:fromage cheddar herbes et ail|bouchees? au fromage|"
                r"ailes? de poulet buffalo|cotes? de porc bbq)\b",
                normalized,
            )
        )
        indexed_processed = indexed_processed or bool(
            re.search(
                r"\b(?:eau gazeifiee|gaufrettes?|smoothie|refreshers?|crispy minis|"
                r"pois et carottes|confiture de fraises|compote aux pommes)\b",
                normalized,
            )
        )
        indexed_processed = indexed_processed or bool(
            re.search(r"\bconfiture de framboise\b", normalized)
        )
        if (
            _GENERIC_INDEX_SNACK_OR_PREPARED.search(normalized)
            or generic_drink
            or non_food
            or flavoured_yogurt
            or indexed_processed
            or insufficient_identity
        ):
            return "indexed_title_outside_culinary_ingredient_scope"
    if (
        _PREPARED_NAME.search(normalized)
        or _COMPOSITE_OR_FLAVOURED_NAME.search(normalized)
        or _REVIEWED_OUT_OF_SCOPE.search(normalized)
    ):
        return "prepared_or_composite_product"
    return None


def _identity_override(value: str) -> str | None:
    rules = (
        (r"\b(?:morceaux? de chocolat|carres? de chocolat|chocolat) mi sucre\b", "brisure_chocolat"),
        (r"\bnoix de coco .*flocons|\bnoix de coco .*dessechee", "noix_coco_rapee"),
        (r"\bpois verts sucres? surgeles?\b", "pois_vert_surgele"),
        (r"\bmelange de noix salees?\b", "noix_melangees"),
    )
    for pattern, canonical_id in rules:
        if re.search(pattern, value):
            return canonical_id
    return None


def _families_for_category(category: str) -> set[str] | None:
    rules = (
        ("/fruits-et-legumes/fruits", {"fruits", "noix_graines"}),
        ("/fruits-et-legumes/legumes/tomates-et-concombres", {"fruits", "legumes"}),
        ("/fruits-et-legumes/legumes", {"legumes", "tomates", "alliums", "herbes", "legumineuses"}),
        ("/fines-herbes-fraiches", {"herbes", "alliums"}),
        ("/boeuf-et-veau", {"boeuf", "veau"}),
        ("/porc", {"porc"}),
        ("/poulet-et-dinde", {"volaille"}),
        ("/agneau-et-gibier", {"agneau", "boeuf", "porc", "volaille"}),
        ("/lapin-et-canard", {"volaille"}),
        ("/poissons", {"poissons", "fruits_de_mer"}),
        ("/fruits-de-mer", {"fruits_de_mer", "poissons"}),
        ("/oeufs", {"oeufs"}),
        ("/fromages", {"fromages", "produits_laitiers"}),
        ("/yogourts", {"produits_laitiers"}),
        ("/laits-cremes-et-beurres", {"produits_laitiers", "huiles"}),
        ("/laits-sans-lactose-et-laits-vegetaux", {"produits_laitiers", "boissons"}),
        ("/epices", {"epices", "herbes", "sauces"}),
        ("/sels-et-poivres", {"epices"}),
        ("/huiles-et-vinaigres", {"huiles", "sauces"}),
        ("/pates-riz-et-feves", {"pates", "riz", "cereales", "legumineuses"}),
        ("/haricots-et-legumineuses", {"legumineuses"}),
        ("/feves-en-conserve", {"legumineuses"}),
        ("/feves-sechees", {"legumineuses"}),
        ("/farines-et-essentiels-de-cuisson", {"farines", "sucres", "patisserie", "epices"}),
        ("/fruits-graines-et-noix", {"fruits", "noix_graines"}),
        ("/chocolat-et-cacao", {"patisserie", "sucres"}),
        ("/sucres-et-edulcorants", {"sucres"}),
        ("/extraits-et-colorants", {"patisserie", "epices"}),
    )
    for part, families in rules:
        if part in category:
            return families
    return None


def _curated_identity(name: str, category: str) -> tuple[str | None, str]:
    """Règles de vocabulaire culinaire revues, indépendantes des marques.

    Elles ne créent jamais un canon. Elles règlent les formes commerciales
    récurrentes dont l'état (sec, conserve, surgelé) est porté par la catégorie
    ou dont le libellé Super C emploie un synonyme absent des alias FCÉN.
    """
    value = normalize_label(name)

    if "/maxi/alimentation/" in category:
        indexed_rules = (
            (r"\blaitue feuille verte\b", "laitue_frisee"),
            (r"\bboisson .*avoine.*non sucre\b|\bboisson .*avoine.*zero sucre\b", "boisson_avoine_non_sucree"),
            (r"\bboisson .*amande.*non sucree?\b", "boisson_amande_non_sucree"),
            (r"\bcrevettes? .*non cuites?\b", "crevette_crue"),
            (r"\bcrevettes? .*cuites?\b", "crevette_cuite"),
            (r"\bkefir nature\b|\blait fermente probiotique kefir nature\b", "kefir_nature"),
            (r"\blait concentre sucre\b", "lait_concentre_sucre"),
            (r"\bchoucroute\b", "choucroute_conserve"),
            (r"\btomates? raisins?\b", "tomate_cerise"),
            (r"\blimes?\b", "lime"),
            (r"\bframboises?\b", "framboise"),
            (r"\bbleuets?\b", "bleuet"),
            (r"\bfraises?\b", "fraise"),
            (r"\bpeches?\b", "peche"),
            (r"\bprunes?\b", "prune"),
            (r"\bkiwis?\b", "kiwi"),
            (r"\bpommes?\b(?! de terre)", "pomme"),
            (r"\bbananes?\b", "banane"),
            (r"\bmangues?\b", "mangue"),
            (r"\braisins? (?:rouges?|verts?|sans pepins|frais)", "raisin"),
            (r"\bmelon d eau\b", "melon_eau"),
            (r"\bcantaloup\b", "melon_cantaloup"),
            (r"\bpamplemousse\b", "pamplemousse"),
            (r"\boranges? (?:navel|sac)|^oranges?$", "orange"),
            (r"\bnectarines?\b", "nectarine"),
            (r"\bpoires?\b", "poire"),
            (r"\bcerises? rouges?\b", "cerise_douce"),
            (r"\bmures?\b", "mure"),
            (r"\bfruits? du dragon\b", "pitahaya_pitaya"),
            (r"\bavocats?\b", "avocat"),
            (r"\bcarottes?\b", "carotte"),
            (r"\bconcombres?\b", "concombre"),
            (r"\bceleri\b(?! rave)", "celeri"),
            (r"\bcourgettes?\b", "courgette"),
            (r"\bepinards?\b", "epinard"),
            (r"\bcoeur de romaine\b|\bsalade romaine\b", "laitue_romaine"),
            (r"\bartichauts?\b", "artichaut"),
            (r"\bpanais\b", "panais"),
            (r"\bradis\b", "radis"),
            (r"\bbrocoli\b", "brocoli"),
            (r"\basperges?\b", "asperge"),
            (r"\bchou fleur\b", "chou_fleur"),
            (r"\bchou rouge\b", "chou_rouge"),
            (r"\bchou vert\b", "chou_vert"),
            (r"\boignons? rouges?\b", "oignon_rouge"),
            (r"\boignons? verts?\b", "oignon_vert"),
            (r"\boignons? doux\b", "oignon_doux"),
            (r"\boignons?\b", "oignon"),
            (r"\bail (?:pele|frais)|\bbulbes? d ail\b|^ail$", "gousse_ail"),
            (r"\bpoivron vert\b", "poivron_vert"),
            (r"\bpoivron rouge\b", "poivron_rouge"),
            (r"\bpoivron jaune\b", "poivron_jaune"),
            (r"\bpommes? de terre russet\b", "pomme_de_terre_russet_chair_et_pelure"),
            (r"\bpommes? de terre jaunes?\b", "pomme_de_terre_jaune"),
            (r"\bpommes? de terre blanches?\b", "pomme_de_terre_blanche_chair_et_pelure"),
            (r"\bpatates? douces?\b", "patate_douce"),
            (r"\bcreme (?:a cuisson )?35\b", "creme_35"),
            (r"\bcreme (?:a cuisson )?15\b", "creme_15"),
            (r"\bcreme a cafe 10\b", "creme_cafe"),
            (r"\blait (?:finement filtre )?3 25\b|\blait homogeneise\b", "lait_325"),
            (r"\blait (?:finement filtre )?2\b|^2 milk", "lait_2"),
            (r"\blait (?:finement filtre )?1\b", "lait_1"),
            (r"\blait ecreme\b", "lait_ecreme"),
            (r"\blait evapore\b", "lait_evapore"),
            (r"\boeufs? (?:extra )?gros\b|\blot de \d+ oeufs\b", "oeuf"),
            (r"\bfromage cheddar\b|\btranches? de fromage (?:extra )?cheddar\b", "cheddar"),
            (r"\bfromage mozzarella\b|\bmozzarellissima\b", "mozzarella"),
            (r"\bfromage rape mozzarella\b", "mozzarella"),
            (r"\bcheddar (?:marbre|fort)\b", "cheddar"),
            (r"\bfromage parmesan\b", "parmesan"),
            (r"\bfromage feta\b", "feta"),
            (r"\bfromage style grec .*feta\b|\btste feta traditionnel\b", "feta"),
            (r"\bfromage suisse\b", "fromage_suisse"),
            (r"\bmascarpone\b", "mascarpone"),
            (r"\bhalloom\b|\bhalloumi\b", "halloumi"),
            (r"\bhavarti\b", "havarti"),
            (r"\bfromage a la creme\b", "fromage_creme"),
            (r"\bbeurre demi sel\b|\bbeurre sale\b", "beurre"),
            (r"\bbeurre non sale\b", "beurre_non_sale"),
            (r"\bhuile de canola\b", "huile_canola"),
            (r"\bhuile d olive\b", "huile_olive"),
            (r"\bhuile vegetale\b", "huile_vegetale"),
            (r"\briz basmati\b", "riz_basmati"),
            (r"\briz (?:au )?jasmin\b", "riz_jasmin"),
            (r"\briz blanc .*grains? longs?\b", "riz_blanc_long"),
            (r"\briz parfume au jasmin\b", "riz_jasmin"),
            (r"\b(?:fettucine|farfalle|spaghettini|macaroni en coudes|pates? (?:penne|rotini|spaghetti|macaroni))\b", "pates_seches"),
            (r"^coudes$|\bpates? grains? entiers? penne\b", "pates_seches"),
            (r"\bavoine .*gros flocons\b", "avoine_flacons"),
            (r"\bcassonade\b", "cassonade"),
            (r"\bsirop de mais\b", "sirop_mais"),
            (r"\bsirop d erable\b", "sirop_erable"),
            (r"\bmoutarde .*dijon\b", "moutarde_dijon"),
            (r"\bvinaigre balsamique\b", "vinaigre_balsamique"),
            (r"\bvinaigre blanc\b|\ble vinaigre naturel\b", "vinaigre_blanc"),
            (r"\bfarine de ble dur\b", "semoule_ble"),
            (r"\blevure rapide\b", "levure_instantanee"),
            (r"\bpois chiches?\b", "pois_chiche_sec"),
            (r"\blentilles? rouges?\b", "lentille_rouge"),
            (r"^lentilles?$", "lentilles_secs"),
            (r"\bpois (?:tendres|grosseurs)\b", "pois_vert_surgele"),
            (r"\bpois sucrelets?\b", "pois_mange_tout"),
            (r"\btofu nature\b", "tofu_ferme"),
            (r"\bpapier de riz\b", "papier_riz"),
            (r"\bchapelure\b", "chapelure"),
            (r"\bnori\b", "algue_nori"),
            (r"\bolives? kalamata\b", "olive_kalamata"),
            (r"\bolives? reines? espagnoles?\b", "olive_verte"),
            (r"\barachides? roties? (?:sans sel|en ecales?)\b", "arachide"),
            (r"\bpistaches? roties? .*non salees?\b", "pistaches"),
            (r"\bnoix de coco\b", "noix_coco_rapee"),
            (r"\bgraines? de cardamome\b", "cardamome_moulue"),
            (r"\bthon pale .*dans de? l eau\b", "thon_conserve_eau"),
            (r"\bthon pale (?:en morceaux|emiette)\b", "thon_conserve_eau"),
            (r"\bfilet de saumon\b", "saumon_filet"),
            (r"\bsaumon sockeye\b", "saumon_rouge_sockeye"),
            (r"\bpetoncles?\b", "petoncle"),
            (r"\bcrevettes? .*crues?\b|\bcrevettes? .*non cuites?\b", "crevette_crue"),
            (r"\bpompano\b", "pompano_floride"),
            (r"\bporc hache\b", "porc_hache"),
            (r"\bpoulet hache\b", "poulet_hache"),
            (r"\bhachis de dinde\b", "dinde_hachee"),
            (r"\bpoitrines? de poulet .*sans peau\b|\bpoitrine de poulet desossee\b", "poulet_poitrine"),
            (r"\bcuisses? de poulet\b", "poulet_cuisse"),
            (r"\blanieres? de poulet\b", "poulet_non_precise"),
            (r"\bailes? de poulet coupees?\b", "aile_poulet"),
            (r"\bdinde .*surgel[eé]e\b", "dinde_avec_peau"),
            (r"\bpoitrine de dinde\b", "poitrine_de_dinde"),
            (r"\b(?:hauts? de )?cuisses? de dinde\b", "cuisse_de_dinde"),
            (r"\bboeuf hache maigre\b", "boeuf_hache_maigre"),
            (r"\bboeuf a fondue\b", "bifteck_boeuf"),
            (r"\bbeurre d arachide\b", "beurre_arachide"),
            (r"\bbeurre d amandes?\b", "noix_amande"),
            (r"\bbeurre vegetal\b", "beurre_vegetalien"),
            (r"\bmargarine\b", "margarine"),
            (r"\btortillas?\b", "tortilla"),
            (r"\bchampignons? blancs?\b|\bchampignons? morceaux\b", "champignon_non_precise"),
            (r"\bbasil(?:ic)? frais\b", "basilic_frais"),
            (r"\btomates? rouges? de serre\b|\btomates? sur vigne\b|\btomate rouge savoura\b|\btomates? roma\b", "tomate"),
            (r"\btomates? cerizo\b", "tomate_cerise"),
            (r"\btomates? cerises? sur la vigne\b", "tomate_cerise"),
            (r"\btomates? coupees? en des\b", "tomate_conserve_des"),
            (r"\bpiments? forts?\b|\bpiments? thai\b", "piment_fort_du_chili_rouge_ou_verts"),
            (r"\bpiments? chipotle\b", "chipotle_adobo"),
            (r"\brondelles? de piments? jalapenos?\b", "piment_jalapeno"),
            (r"\bpoivron orange\b", "tomate_orange"),
            (r"\bpoivrons? doux melanges?\b|\bpoivrons? paquet\b", "poivron_melange"),
            (r"\bpoivrons? pacquet\b", "poivron_melange"),
            (r"\bpetits? poivrons? doux\b", "poivron_melange"),
            (r"\bmandarines?\b", "tangerine_mandarine"),
            (r"\bmelon miel\b|\bmelons? hami\b", "melon"),
            (r"\bcourges? spaghetti\b", "courge_d_hiver_spaghetti"),
            (r"\bcourge musquee\b", "courge_musquee"),
            (r"\bpm terre .*fingerling\b|\bpommes? de terre little gems\b", "pomme_de_terre"),
            (r"\bchoux? taiwanais\b", "chou_de_chine_pe_tsai"),
            (r"\bharicots? verts? a la francaise\b", "haricot_vert"),
            (r"\bananas? en morceaux\b", "ananas"),
            (r"\bmaquereau espagnol\b", "maquereau_espagnol_chinchard"),
            (r"\bbouillon de poulet\b", "bouillon_poulet"),
            (r"\brelish\b", "relish"),
            (r"\bproduit laitier sans lactose 2\b|\blait .*ultrafiltre.*2\b|\bpurfiltre lait .*2\b", "lait_2"),
            (r"\blait .*ultrafiltre.*3 25\b", "lait_325"),
            (r"\bsans lactose lait .*1\b", "lait_1"),
            (r"\bproduit laitier .*ecreme 0\b", "lait_ecreme"),
            (r"\byogourt grec .*nature\b|\bgrec yogourt .*nature\b", "yogourt_grec"),
            (r"\byogourt .*nature\b", "yogourt_nature"),
            (r"\byogourt dahi\b", "yogourt_nature"),
            (r"\bfromage farmer s marbre\b", "cheddar"),
            (r"\boeufs? calibre gros\b|\boeufs? omega 3\b", "oeuf"),
            (r"\bzero iceberg\b", "laitue_iceberg"),
            (r"\bmayonnaise\b", "mayonnaise"),
        )
        for pattern, canonical_id in indexed_rules:
            if re.search(pattern, value):
                return canonical_id, "curated_indexed_title_identity"

    if "/yogourts" in category and "nature" in value:
        return (
            "yogourt_grec" if "grec" in value else "yogourt_nature",
            "curated_plain_yogurt_identity",
        )
    if "/cremes-et-colorants-a-cafe" in category:
        if re.search(r"\b(?:15|18)\b", value):
            return "creme_15", "curated_cream_fat_class"
        if "35" in value:
            return "creme_35", "curated_cream_fat_class"
        if re.search(r"\b10\b", value):
            return "creme_cafe", "curated_cream_fat_class"

    if "/pates-riz-et-feves/pates" in category or "/nouilles-et-vermicelle" in category:
        if not re.search(
            r"\b(?:au|aux|avec|fromage|epinard|boeuf|poulet|assaisonn|instantan)\b",
            value,
        ):
            return "pates_seches", "curated_plain_dry_pasta_identity"
    if "/pates-et-sauces-pour-pates" in category and re.match(
        r"^(?:pates?|lasagnes?)\b", value
    ):
        return "pates_seches", "curated_plain_dry_pasta_identity"

    if "/tomates-et-concombres" in category:
        if "concombre" in value or "cornichon" in value:
            return "concombre", "curated_fresh_produce_identity"
        if "cerise" in value:
            return "tomate_cerise", "curated_fresh_produce_identity"
        return "tomate", "curated_fresh_produce_identity"

    if "/fines-herbes-fraiches" in category:
        fresh_herbs = (
            (r"\bcoriandre\b", "coriandre_fraiche"),
            (r"\baneth\b", "aneth_frais"),
            (r"\bmenthe\b", "menthe_fraiche"),
            (r"\bthym\b", "thym_frais"),
            (r"\bromarin\b", "romarin_frais"),
            (r"\borigan\b", "origan_frais"),
        )
        for pattern, canonical_id in fresh_herbs:
            if re.search(pattern, value):
                return canonical_id, "curated_fresh_herb_identity"

    if "/agrumes" in category and "mineola" in value:
        return "tangerine_mandarine", "curated_citrus_variety_identity"

    keyword_rules = (
        (r"\broquefort\b", "fromage_bleu"),
        (r"\bbrie\b", "fromage_brie"),
        (r"\bcamembert\b", "fromage_camembert"),
        (r"\bgouda\b", "fromage_gouda"),
        (r"\bemmental\b", "fromage_suisse"),
        (r"\bparmigiano|grana padano\b", "parmesan"),
        (r"\bfarine (?:d |de )?avoine\b", "farine_d_avoine_grains_entiers"),
        (r"\bfarine de? sarasin\b", "farine_de_sarrasin_a_grain_entier"),
        (r"\bharicots? francais verts?\b", "haricot_vert"),
        (r"\bfleurettes? de chou fleur\b", "chou_fleur"),
        (r"\brapini\b", "rapini_brocoli_raab"),
        (r"\bpoireaux?\b", "poireau"),
        (r"\bgingembre\b", "gingembre_frais"),
        (r"\bfenouil\b", "fenouil_bulbe"),
        (r"\bfruit du dragon\b", "pitahaya_pitaya"),
        (r"\bgrenadille|fruit de la passion\b", "grenadille_fruit_de_la_passion"),
        (r"\bcarambole\b", "carambole_fruit_etoile"),
        (r"\bplaquemine\b", "kaki_diospyros_kaki"),
        (r"\bchayote\b", "chayotte_fruit"),
        (r"\bdaikon\b", "radis_orientaux_daikon"),
        (r"\bjicama\b", "doliques_bulbeux_jicama"),
        (r"\byucca\b", "manioc"),
        (r"\bokra\b", "okra_gombo"),
        (r"\bgourganes?\b", "gourganes_feves_des_marais_fava"),
        (r"\bedamames?\b|\bfeves? de soya\b", "edamame_surgele"),
        (r"\bnoisettes?\b", "noisettes_avelines_ou_coudres"),
        (r"\bpignons?\b", "noix_de_pins_pignons_pignes"),
        (r"\bsaindoux\b", "saindoux_porc"),
        (r"\bfeuilles? d origan\b|\borigan\b", "origan_seche"),
        (r"\bfeuilles? de romarin\b|\bromarin\b", "romarin_seche"),
        (r"\bfeuilles? de thym\b|\bthym\b", "thym_seche"),
        (r"\baneth\b", "aneth_seche"),
        (r"\bpersil (?:en flocons|seche)\b", "persil_seche"),
        (r"\bsarriette\b", "sarriette_moulue"),
        (r"\bgraines? de coriandre\b", "coriandre_cilantro_graines"),
        (r"\bepices? (?:a )?bifteck de montreal\b", "epices_steak_montreal"),
        (r"\boignon (?:emince )?deshydrate\b", "poudre_oignon"),
        (r"\bestragon frais\b", "estragon_seche"),
        (r"\bsauge fraiche\b", "sauge_moulue"),
        (r"\bfeuilles? de laurier fraiches?\b", "feuille_laurier"),
        (r"\bcoriandre(?: en pot)?\b", "coriandre_fraiche"),
        (r"\baneth(?: en pot)?\b", "aneth_frais"),
        (r"\bmenthe(?: en pot)?\b", "menthe_fraiche"),
        (r"\bthym en pot\b", "thym_frais"),
        (r"\blaitue boston\b", "laitue_boston"),
        (r"\blaitue (?:a )?feuilles? rouges?\b", "laitue_feuilles_rouges"),
        (r"\blaitue frisee\b", "laitue_frisee"),
        (r"\bendive\b", "endive_de_belgique_chicoree_de_bruxelles_ou_witloof"),
        (r"\bchicoree\b", "chicoree_feuilles_cichorium_intybus"),
        (r"\bscarole\b", "scarole_ou_endive_cichorium_endivia"),
        (r"\bpissenlit\b", "pissenlit_feuilles"),
        (r"\bcresson\b", "cresson_de_fontaine"),
        (r"\bcourge poivree\b", "courge_d_hiver_courge_poivree_courgeon"),
        (r"\bcourge spaghetti\b", "courge_d_hiver_spaghetti"),
        (r"\bcornichons? frais\b", "concombre"),
        (r"\bmais\b", "mais"),
        (r"\bharicots? jaunes?\b", "haricots_italiens_jaunes_ou_verts"),
        (r"\bpois sucres?\b", "pois_mange_tout"),
        (r"\bcerises? rainier\b|\bcerises? douces?\b|^cerises?$", "cerise_douce"),
        (r"\bboisson (?:au|de) soya\b", "lait_soya"),
        (r"\bthon\b.*\bdans l eau\b", "thon_conserve_eau"),
        (r"\bthon\b.*\bhuile\b", "thon_conserve_huile"),
        (r"\bsaumon rose\b", "saumon_rose_conserve"),
        (r"\bpalourdes?\b", "mye_palourde"),
        (r"\bpaves? de thon crus?\b", "thon_a_nageoires_jaunes"),
        (r"\bsole\b", "filet_sole"),
        (r"\bfilet mignon\b", "bifteck_de_filet_de_boeuf"),
        (r"\bfaux filet\b", "boeuf_faux_filet"),
        (r"\bcontre filet\b", "bifteck_de_contre_filet"),
        (r"\bsurlonge\b", "boeuf_bifteck_surlonge"),
        (r"\bpalette\b", "boeuf_roti_palette"),
        (r"\bcubes? de boeuf|\blanieres? de boeuf\b", "boeuf_ragout"),
        (r"\bbifteck\b|\bsteak emince\b", "bifteck_boeuf"),
        (r"\bcotes? de (?:dos de )?porc\b", "cote_levee_porc"),
        (r"\bescalopes? de .*porc\b", "escalope_porc"),
        (r"\bfoies? de porc\b", "foie_de_porc"),
        (r"\b(?:longe|roti).*porc\b|\bcubes? de porc\b", "porc_non_precise"),
        (r"\bfoies? de boeuf\b", "foie_de_boeuf"),
        (r"\b(?:haut|hauts) de cuisses? de poulet\b", "poulet_cuisse"),
        (r"\bdinde entiere\b|^dinde surgele", "dinde_avec_peau"),
        (r"\bveau .*hache\b", "veau_hache"),
        (r"\bfarine preparee pour gateaux\b", "farine_gateaux"),
        (r"\bpate de tomates?\b", "pate_tomate"),
        (r"\bsalsa\b", "salsa"),
        (r"\blait de (?:noix de )?coco\b", "lait_coco_conserve"),
        (r"\bpepites? de chocolat blanc\b", "chocolat_blanc"),
        (r"\bburgol\b", "boulgour"),
        (r"\bgraines? .*chia\b", "graine_chia"),
        (r"\bdatte", "datte_sechee"),
        (r"\bvinaigre de vin blanc\b|\bvinaigre pour marinades\b", "vinaigre_blanc"),
        (r"\bextrait d amande\b", "extrait_amande"),
        (r"\bshortening\b", "shortening_vegetal"),
        (r"\bail (?:hache|emince)\b", "gousse_ail"),
        (r"\bail granule\b", "poudre_ail"),
        (r"\bgraines? de carvi\b", "carvi_graines"),
        (r"\bcerfeuil\b", "cerfeuil_seche"),
        (r"\bchili broye\b", "flocon_piment"),
        (r"\bestragon\b", "estragon_seche"),
        (r"\bgraines? de sesame\b", "graine_sesame"),
        (r"\bmarjolaine\b", "marjolaine_sechee"),
        (r"\bgraines? de pavot\b", "pavot_graines"),
        (r"^persil$", "persil_seche"),
        (r"\bsauge rapee\b", "sauge_moulue"),
        (r"\bepices? [àa] steak (?:style )?montreal\b", "epices_steak_montreal"),
        (r"\bcurcuma\b", "curcuma_moulu"),
        (r"\bfarine non blanchie\b", "farine_tout_usage"),
        (r"\bpates? (?:cavatappi|macaroni en coude)\b", "pates_seches"),
        (r"\btomates? en des\b", "tomate_conserve"),
        (r"\bketchup\b", "ketchup"),
        (r"\briz .*\betuve\b", "riz_etuve"),
        (r"\bsemoule de ble\b", "semoule_ble"),
        (r"\blevure pour four [àa] pain\b", "levure_seche_active"),
        (r"\bgelatine\b", "gelatine_poudre"),
        (r"\bflocons? d avoine\b", "avoine_flacons"),
        (r"\bpate de sesame\b", "tahini"),
        (r"\bsardines?\b", "sardine_conserve"),
        (r"\bthon pale entier\b", "thon_conserve_eau"),
        (r"\bsauce bbq\b", "sauce_barbecue"),
        (r"\bpates? (?:pappardelle|tagliatelle) aux oeufs\b", "nouille_oeuf"),
        (r"\bpetits pois\b|\bpois verts tendres\b|\bpois de grosseurs\b|^pois surgeles$", "pois_vert_surgele"),
        (r"\bgros haricots? de lima\b", "haricot_lima_conserve"),
        (r"\bfeves? rouges?\b", "haricot_rouge_conserve"),
        (r"\bharicots? de soissons\b", "haricot_blanc_conserve"),
        (r"\bdoliques? [àa] oeil noir\b", "haricots_a_oeil_noir_dolique_communs_secs"),
        (r"\bharicots? romains?\b", "haricots_canneberge_romain_secs"),
        (r"\bpois jaunes? casses?\b", "pois_casse_sec"),
        (r"\bmalanga\b", "yautia_tannier_chou_des_caraibes"),
        (r"\beddoe\b", "taro"),
        (r"\bfenugrec\b", "graines_de_fenugrec"),
        (r"\bpiment (?:fort jaune|cubanelle|thai)\b|\bpiments thai\b", "piment_fort_du_chili_rouge_ou_verts"),
        (r"\bcourge (?:buttercup|delicata|sweet mama)\b", "courge_d_hiver"),
        (r"\brabioles?\b", "navet"),
        (r"\bhuitres? malpeque\b", "huitre_atlantique_sauvage"),
        (r"\bcrevettes? .*petoncles?\b", "petoncle"),
        (r"\bdorade\b", "dorade_royale"),
        (r"\bfoie de veau\b|\btranches? de foie de veau\b", "foie_veau"),
        (r"\bjarret de boeuf\b", "jarret_boeuf"),
        (r"\bviande de cerf\b", "viande_cerf"),
        (r"\bviande de bison\b", "viande_bison"),
        (r"\bviande de cheval\b", "viande_cheval"),
        (r"\bgigot d agneau\b", "gigot_agneau"),
        (r"\bhaloumi\b|\bhalloumi\b", "halloumi"),
        (r"\bstyle suisse\b", "fromage_suisse"),
        (r"\bfromage .*persille\b", "fromage_bleu"),
        (r"\bfromage brick\b", "fromage_brick"),
        (r"\bjambon fume\b|\bepaule picnic de porc fumee\b", "jambon_cuit"),
        (r"\btomates? .*broy[eé]es?\b|\btomates? etuvees?\b", "tomate_conserve"),
        (r"\btomates? sechees?\b", "tomate_sechee"),
        (r"\bedulcorant .*stevia\b", "edulcorant_stevia"),
        (r"\bedulcorant .*sucralose\b|\bedulcorant sans calories\b", "edulcorant_sucralose"),
        (r"\bmarinade teriyaki\b", "sauce_soja"),
        (r"\bsauce piri piri\b", "sauce_piquante"),
        (r"\bbouillon liquide de boeuf\b", "bouillon_boeuf"),
        (r"\bbeurre sale\b", "beurre"),
        (r"\bgros oeufs\b", "oeuf"),
        (r"\bboisson .*soya\b", "lait_soya"),
        (r"\bnouilles? ramen\b", "nouille_ramen_instantanee"),
        (r"\bbrisures? de creme blanche\b", "chocolat_blanc"),
        (r"\bharicots? verts? coupes?\b", "haricot_vert"),
        (r"\bmoutarde de dijon\b", "moutarde_dijon"),
        (r"\blasagne direct au four\b", "lasagne_seche"),
        (r"\benduit .*huile d olive\b", "huile_olive"),
        (r"\bcubes? de cuisse de boeuf\b", "boeuf_ragout"),
        (r"\broti du roi\b", "bifteck_boeuf"),
        (r"\bfromage .*persillee?\b", "fromage_bleu"),
    )
    for pattern, canonical_id in keyword_rules:
        if re.search(pattern, value):
            return canonical_id, "curated_food_synonym_identity"

    if "/feves-sechees" in category:
        return _legume_identity(value, canned=False), "curated_legume_state_identity"
    if "/feves-en-conserve" in category or "/haricots-et-legumineuses" in category:
        return _legume_identity(value, canned=True), "curated_legume_state_identity"
    return None, ""


def _legume_identity(value: str, *, canned: bool) -> str | None:
    state = "conserve" if canned else "sec"
    rules = (
        (r"pois chiches?|garbanzo", f"pois_chiche_{state}"),
        (r"haricots? noirs?", f"haricot_noir_{state}"),
        (r"haricots? rouges?", "haricot_rouge_conserve" if canned else "haricots_rouges_tous_les_types_secs"),
        (r"haricots? blancs?|cannellini|navy", "haricot_blanc_conserve" if canned else "haricots_blancs_secs"),
        (r"haricots? pinto", "haricot_pinto_conserve" if canned else "haricots_pinto_secs"),
        (r"lentilles? rouges?", "lentille_rouge"),
        (r"lentilles? brunes?", "lentille_brune"),
        (r"lentilles?", "lentille_conserve" if canned else "lentilles_secs"),
    )
    for pattern, canonical_id in rules:
        if re.search(pattern, value):
            return canonical_id
    return None


def _entry_score(product_name: str, entry: _Canonical) -> float:
    product = normalize_label(product_name)
    product_tokens = _reduced_tokens(product)
    best = 0.0
    for label in entry.labels:
        label_tokens = _reduced_tokens(label)
        if not label_tokens:
            continue
        intersection = product_tokens & label_tokens
        recall = len(intersection) / len(label_tokens)
        precision = len(intersection) / max(1, len(product_tokens))
        token_score = (2 * recall * precision / (recall + precision)) if intersection else 0
        sequence = SequenceMatcher(None, product, label).ratio()
        phrase = 1.0 if re.search(rf"\b{re.escape(label)}\b", product) else 0.0
        best = max(best, 0.50 * token_score + 0.35 * sequence + 0.15 * phrase)
    return best


def _reduced_tokens(value: str) -> set[str]:
    return {
        _singular(token)
        for token in value.split()
        if token not in _MARKETING_TOKENS and len(token) > 1
    }


def _singular(value: str) -> str:
    if value.endswith("eaux") and len(value) > 5:
        return value[:-1]
    if value.endswith("aux") and len(value) > 4:
        return value[:-3] + "al"
    if value.endswith("s") and len(value) > 3:
        return value[:-1]
    return value
