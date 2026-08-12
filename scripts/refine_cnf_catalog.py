"""Raffine le FCÉN 2026 en décisions sûres pour le catalogue Souschef.

Ce script ne traite pas le FCÉN comme un catalogue prêt à importer. Il ne
retient que des aliments simples dans un état achetable explicite, consolide
les doublons exacts et met de côté toute ressemblance non exacte. Le résultat
versionné est ensuite consommé par ``generate_catalog.py``.

Usage depuis la racine du dépôt::

    python scripts/refine_cnf_catalog.py --archive <cnf-2026.zip>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.ingestion.cnf import parse_cnf_archive  # noqa: E402
from app.ingestion.ingredient_curation import (  # noqa: E402
    SIMILARITY_THRESHOLD,
    label_similarity,
    normalize_label,
)
from catalog_seed_data import alias_rows, ingredient_rows  # noqa: E402

SOURCE_VERSION = "2026"
RULES_VERSION = "cnf-catalog-quality-v1"
REVIEWER = RULES_VERSION
GENERAL_ALLOWED_GROUPS = frozenset({"2", "4", "9", "11", "12", "15", "16", "20"})
ALLOWED_GROUPS = GENERAL_ALLOWED_GROUPS | {"1", "5", "10", "13"}
ATTACH_OVERRIDES = {
    # Équivalences culinaires évidentes que les formulations FCÉN n'expriment
    # pas avec le même ordre de mots que le socle existant.
    "3252": "haricot_noir_sec",
    "4460": "pate_soba",
    # Seconde passe : ressemblances revues qui désignent réellement le même
    # aliment achetable. Elles sont rattachées plutôt que dupliquées.
    "169": "piment_jamaique",
    "172": "feuille_laurier",
    "184": "graine_aneth",
    "1573": "raisin",
    "1705": "bleuet",
    "1718": "raisin",
    "1747": "framboise",
    "1749": "fraise",
    "2038": "bok_choy",
    "2067": "coriandre_fraiche",
    "2091": "gingembre_frais",
    "2144": "oignon_vert",
    "2145": "oignon_vert",
    "2151": "pois_vert_surgele",
    "2274": "chataigne_eau",
    "2399": "champignon_blanc",
    "2444": "rutabaga",
    "2451": "courge_musquee",
    "2460": "tomate",
    "2500": "betterave",
    "2608": "tahini",
    "3211": "crevette_crue",
    "3213": "petoncle",
    "3389": "pois_chiche_sec",
    "4471": "riz_blanc_long",
    "4487": "sarrasin_grain",
    "4848": "concombre",
    "5709": "noix_cajou",
}

# Ces lignes passent le filtre lexical « aliment simple », mais leur instantané
# décrit en réalité un mélange ou une fraction nutritionnelle, pas une identité
# de recette autonome. La décision explicite évite de relâcher le filtre global.
EXCLUDE_OVERRIDES = frozenset({
    "2155",  # pois et carottes
    "2158",  # pois et oignons
    "2417",  # chair de pomme de terre isolée
    "2418",  # pelure de pomme de terre isolée
    "2505",  # chair et pelure (entrée nutritionnelle)
    "5508",  # mélange maïs-canola
    "5510",  # mélange canola-soya
    "5622",  # mélange maïs-arachide-olive
    "5842",  # peau de poisson isolée
    "5913",  # peau de poisson isolée
    "7050",  # huile avec morceaux ajoutés
})

# Les groupes animaux contiennent des centaines de découpes nutritionnelles.
# Cette liste positive ne retient que des produits crus nommables et achetables;
# elle évite de transformer un filtre de groupe en import massif implicite.
ADDITIONAL_RAW_ANIMAL_LABELS = {
    # Œufs
    "88": ("Œuf de canard", "Duck egg"),
    "89": ("Œuf d’oie", "Goose egg"),
    "90": ("Œuf de caille", "Quail egg"),
    "91": ("Œuf de dinde", "Turkey egg"),
    # Volaille
    "571": ("Abats de poulet", "Chicken giblets"),
    "574": ("Gésier de poulet", "Chicken gizzard"),
    "576": ("Cœur de poulet", "Chicken heart"),
    "578": ("Foie de poulet", "Chicken liver"),
    "616": ("Cou de poulet", "Chicken neck"),
    "662": ("Canard avec peau", "Duck meat with skin"),
    "664": ("Viande de canard", "Duck meat"),
    "666": ("Foie de canard", "Duck liver"),
    "668": ("Poitrine de canard", "Duck breast"),
    "669": ("Oie avec peau", "Goose meat with skin"),
    "671": ("Viande d’oie", "Goose meat"),
    "673": ("Foie d’oie", "Goose liver"),
    "674": ("Pintade avec peau", "Guinea fowl with skin"),
    "676": ("Faisan avec peau", "Pheasant with skin"),
    "678": ("Poitrine de faisan", "Pheasant breast"),
    "679": ("Cuisse de faisan", "Pheasant leg"),
    "680": ("Caille avec peau", "Quail with skin"),
    "682": ("Poitrine de caille", "Quail breast"),
    "683": ("Pigeonneau avec peau", "Squab with skin"),
    "685": ("Poitrine de pigeonneau", "Squab breast"),
    "688": ("Dinde avec peau", "Turkey meat with skin"),
    "690": ("Viande de dinde", "Turkey meat"),
    "694": ("Abats de dinde", "Turkey giblets"),
    "696": ("Gésier de dinde", "Turkey gizzard"),
    "698": ("Cœur de dinde", "Turkey heart"),
    "700": ("Foie de dinde", "Turkey liver"),
    "702": ("Cou de dinde", "Turkey neck"),
    "714": ("Poitrine de dinde", "Turkey breast"),
    "716": ("Cuisse de dinde", "Turkey leg"),
    "718": ("Aile de dinde", "Turkey wing"),
    # Porc
    "1755": ("Porc non précisé", "Unspecified pork"),
    "1757": ("Gras de dos de porc", "Pork back fat"),
    "1758": ("Flanc de porc", "Pork belly"),
    "1761": ("Cuisse de porc", "Pork leg"),
    "1813": ("Épaule de porc", "Pork shoulder"),
    "1832": ("Cervelle de porc", "Pork brain"),
    "1834": ("Intestins de porc", "Pork intestines"),
    "1836": ("Oreilles de porc", "Pork ears"),
    "1838": ("Pieds de porc", "Pork feet"),
    "1839": ("Cœur de porc", "Pork heart"),
    "1841": ("Bajoue de porc", "Pork jowl"),
    "1843": ("Panne de porc", "Pork leaf fat"),
    "1844": ("Foie de porc", "Pork liver"),
    "1846": ("Poumons de porc", "Pork lungs"),
    "1849": ("Pancréas de porc", "Pork pancreas"),
    "1851": ("Rate de porc", "Pork spleen"),
    "1853": ("Estomac de porc", "Pork stomach"),
    "1854": ("Langue de porc", "Pork tongue"),
    "1880": ("Queue de porc", "Pork tail"),
    "1893": ("Côtes de dos de porc", "Pork back ribs"),
    "1935": ("Rognon de porc", "Pork kidney"),
    # Bœuf
    "2650": ("Cervelle de bœuf", "Beef brain"),
    "2653": ("Cœur de bœuf", "Beef heart"),
    "2658": ("Poumons de bœuf", "Beef lungs"),
    "2661": ("Pancréas de bœuf", "Beef pancreas"),
    "2663": ("Rate de bœuf", "Beef spleen"),
    "2666": ("Thymus de bœuf", "Beef thymus"),
    "2668": ("Langue de bœuf", "Beef tongue"),
    "2670": ("Tripes de bœuf", "Beef tripe"),
    "2676": ("Pointe de poitrine de bœuf", "Beef brisket"),
    "2787": ("Rognon de bœuf", "Beef kidney"),
    "2788": ("Foie de bœuf", "Beef liver"),
    "6018": ("Gras de bœuf", "Beef fat"),
    "6022": ("Bifteck de flanc de bœuf", "Beef flank steak"),
    "6079": ("Rôti de côte de bœuf", "Beef rib roast"),
    "6109": ("Bifteck de contre-filet", "Strip loin steak"),
    "6115": ("Bifteck d’aloyau", "T-bone steak"),
    "6125": ("Rôti de filet de bœuf", "Beef tenderloin roast"),
    "6131": ("Bifteck de filet de bœuf", "Beef tenderloin steak"),
}
LABEL_OVERRIDES = {
    # Révision éditoriale des formulations FCÉN inversées, fautives ou trop
    # nutritionnelles. Les deux langues restent directement traçables dans
    # candidate_snapshot.
    "169": ("Piment de la Jamaïque moulu", "Ground allspice"),
    "170": ("Graines d’anis", "Anise seeds"),
    "175": ("Graines de céleri", "Celery seeds"),
    "179": ("Clous de girofle moulus", "Ground cloves"),
    "180": ("Feuilles de coriandre séchées", "Dried cilantro leaves"),
    "187": ("Graines de fenugrec", "Fenugreek seeds"),
    "199": ("Piment de Cayenne", "Cayenne pepper"),
    "416": ("Huile de son de riz", "Rice bran oil"),
    "417": ("Huile de germe de blé", "Wheat germ oil"),
    "435": ("Huile de graines de pavot", "Poppy seed oil"),
    "444": ("Huile de babassu", "Babassu oil"),
    "452": ("Huile de moutarde", "Mustard oil"),
    "2128": ("Feuilles de moutarde surgelées", "Frozen mustard greens"),
    "2140": ("Oignons hachés surgelés", "Frozen chopped onions"),
    "2268": ("Feuilles et racines de navet surgelées", "Frozen turnip greens and roots"),
    "2460": ("Tomate rouge", "Red tomato"),
    "2544": ("Noix du Brésil non blanchies", "Unblanched Brazil nuts"),
    "2984": ("Anchois européen", "European anchovy"),
    "3297": ("Haricots mungo secs", "Dry mung beans"),
    "4415": ("Maïs jaune sec", "Dry yellow corn"),
    "4488": ("Farine de sarrasin à grain entier", "Whole-grain buckwheat flour"),
    "4501": ("Farine tout usage blanchie", "Bleached all-purpose flour"),
    "5535": ("Vermicelles de soya secs", "Dry soy vermicelli"),
}

_COOKED_OR_COMPOSITE_FR = re.compile(
    r"\b(?:cuit(?:e|es|s)?|bouilli(?:e|es|s)?|frit(?:e|es|s)?|"
    r"grill[ée](?:e|es|s)?|r[oô]ti(?:e|es|s)?|saut[ée](?:e|es|s)?|"
    r"mijot[ée](?:e|es|s)?|chauff[ée](?:e|es|s)?|pan[ée](?:e|es|s)?|"
    r"recette|restaurant|fait(?:e)? maison|avec|assaisonn(?:ements?|[ée](?:e|es|s)?)|"
    r"m[ée]langes?|mac[ée]doine|succotash|saveur|ar[oô]matis[ée](?:e|es|s)?|"
    r"enrichi(?:e|es|s)?|fortifi[ée](?:e|es|s)?|pr[ée]paration|"
    r"sucr[ée](?:e|es|s)?|sal[ée](?:e|es|s)?|pr[ée]par[ée](?:e|es|s)?)\b"
)
_COOKED_OR_COMPOSITE_EN = re.compile(
    r"\b(?:cooked|boiled|fried|grilled|broiled|roasted|toasted|stir-fried|"
    r"stewed|heated|breaded|recipe|restaurant|homemade|with sauce|seasoned|"
    r"sweetened|salted|prepared|seasonings?|mix(?:es)?|flavou?red|enriched|"
    r"fortified|self-rising|cooking spray)\b"
)
_STATE_FR = re.compile(
    r"\b(?:cru(?:e|es|s)?|frais|fra[iî]che(?:s)?|sec(?:s)?|s[ée]ch[ée](?:e|es|s)?|"
    r"d[ée]shydrat[ée](?:e|es|s)?|non cuit(?:e|es|s)?|non pr[ée]par[ée](?:e|es|s)?|"
    r"congel[ée](?:e|es|s)?|surgel[ée](?:e|es|s)?)\b"
)
_STATE_EN = re.compile(
    r"\b(?:raw|fresh|dry|dried|dehydrated|uncooked|unprepared|frozen)\b"
)
_DROP_SEGMENT_FR = re.compile(
    r"^(?:cru(?:e|es|s)?|frais|fra[iî]che(?:s)?|sec(?:s)?|s[ée]ch[ée](?:e|es|s)?|"
    r"d[ée]shydrat[ée](?:e|es|s)?|non cuit(?:e|es|s)?|non pr[ée]par[ée](?:e|es|s)?|"
    r"congel[ée](?:e|es|s)?|surgel[ée](?:e|es|s)?|esp[èe]ces diverses|"
    r"toutes vari[ée]t[ée]s(?: commerciales)?|m[uû]r(?:e|es|s)?|moyenne?|"
    r"durant toute l.ann[ée]e|grains m[uû]rs?|autochtone)$"
)
_DROP_SEGMENT_EN = re.compile(
    r"^(?:raw|fresh|dry|dried|dehydrated|uncooked|unprepared|frozen|"
    r"mixed species|all (?:commercial )?varieties|ripe|average|year round|"
    r"mature seeds?|indigenous)$"
)


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _parts(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _contains(pattern: re.Pattern[str], value: str) -> bool:
    return pattern.search(_fold(value)) is not None


def _without_unprepared(value: str) -> str:
    folded = _fold(value)
    return re.sub(r"\b(?:non prepare(?:e|es|s)?|unprepared)\b", "", folded)


def quality_reason(row: dict) -> str | None:
    """Retourne ``None`` seulement pour une ligne simple et achetable."""
    group = row["cnf_food_group_code"]
    fr = row["food_description_fr"]
    en = row["food_description_en"]
    if str(row.get("food_code") or "") in ADDITIONAL_RAW_ANIMAL_LABELS:
        return None
    if group not in GENERAL_ALLOWED_GROUPS:
        return "group_outside_ingredient_scope"
    if not fr.strip() or not en.strip():
        return "missing_bilingual_identity"
    if len(fr) > 160 or len(en) > 160 or fr.count(",") > 5 or en.count(",") > 5:
        return "description_too_specific"

    check_fr = _without_unprepared(fr)
    check_en = _without_unprepared(en)
    if _COOKED_OR_COMPOSITE_FR.search(check_fr) or _COOKED_OR_COMPOSITE_EN.search(check_en):
        return "cooked_seasoned_or_composite"

    fr_n = _fold(fr)
    en_n = _fold(en)
    if group == "2":
        if fr_n.startswith("vinaigre,") and fr.count(",") <= 2:
            return None
        if fr_n.startswith("epices,") and fr.count(",") <= 4:
            return None
        return "not_a_simple_spice_or_vinegar"
    if group == "4":
        simple_fat = fr_n.startswith(("huile vegetale,", "gras animal,"))
        specialized = any(
            token in fr_n
            for token in ("acide linoleique", "acide oleique", "lecithine")
        )
        return None if simple_fat and fr.count(",") <= 2 and not specialized else "not_a_simple_oil_or_fat"
    if group == "9":
        if "jus" in fr_n or "juice" in en_n:
            return "juice_or_fruit_product"
        raw = re.search(r"\bcru(?:e|es|s)?\b", fr_n) and re.search(r"\braw\b", en_n)
        return None if raw else "fruit_not_raw"
    if group == "11":
        raw = re.search(r"\b(?:cru(?:e|es|s)?|fra[iî]che(?:s)?)\b", fr_n)
        raw = raw and re.search(r"\b(?:raw|fresh)\b", en_n)
        frozen = re.search(r"\b(?:congele(?:e|es|s)?|surgele(?:e|es|s)?)\b", fr_n)
        frozen = frozen and "non prepare" in fr_n and "frozen" in en_n and "unprepared" in en_n
        return None if raw or frozen else "vegetable_not_raw_or_unprepared_frozen"
    if group == "12":
        valid_fr = re.search(r"\b(?:cru(?:e|es|s)?|sec(?:s)?|seche(?:e|es|s)?|deshydrate(?:e|es|s)?)\b", fr_n)
        valid_en = re.search(r"\b(?:raw|dry|dried|dehydrated|unroasted)\b", en_n)
        return None if valid_fr and valid_en else "nut_or_seed_not_raw_or_dried"
    if group == "15":
        if any(token in fr_n for token in ("oesophage", "oeufs", "rogue")):
            return "seafood_tissue_not_recipe_identity"
        raw_fr = re.search(r"\bcru(?:e|es|s)?\b", fr_n)
        return None if raw_fr and re.search(r"\braw\b", en_n) else "seafood_not_raw"
    if group == "16":
        if "conserve" in fr_n or "canned" in en_n:
            return "legume_canned_or_composite"
        dry_fr = re.search(r"\b(?:sec(?:s)?|seche(?:e|es|s)?)\b", fr_n)
        return None if dry_fr and re.search(r"\bdry\b", en_n) else "legume_not_dry"
    if group == "20":
        dry = re.search(r"\b(?:sec(?:s)?|seche(?:e|es|s)?|deshydrate(?:e|es|s)?)\b", fr_n)
        dry = dry and re.search(r"\b(?:dry|dried|dehydrated)\b", en_n)
        flour = any(token in fr_n for token in ("farine", "fecule"))
        return None if dry or flour else "grain_not_dry_or_flour"
    raise AssertionError(group)


def _clean_parts(value: str, language: str, *, drop_prefix: bool = True) -> list[str]:
    parts = _parts(value)
    if drop_prefix and parts:
        parts = parts[1:]
    drop = _DROP_SEGMENT_FR if language == "fr" else _DROP_SEGMENT_EN
    return [part for part in parts if not drop.fullmatch(_fold(part))]


def _sentence(parts: list[str]) -> str:
    value = " ".join(parts)
    value = re.sub(r"\s+", " ", value).strip(" .")
    value = re.sub(r"\beuerop[ée]en\b", "européen", value, flags=re.IGNORECASE)
    return value[:1].upper() + value[1:] if value else ""


def proposed_labels(row: dict) -> tuple[str, str]:
    """Produit un libellé de catalogue concis, jamais le texte FCÉN brut."""
    if row["food_code"] in ADDITIONAL_RAW_ANIMAL_LABELS:
        return ADDITIONAL_RAW_ANIMAL_LABELS[row["food_code"]]
    if row["food_code"] in LABEL_OVERRIDES:
        return LABEL_OVERRIDES[row["food_code"]]
    group = row["cnf_food_group_code"]
    fr, en = row["food_description_fr"], row["food_description_en"]
    fr_n = _fold(fr)

    if group == "2" and fr_n.startswith("vinaigre,"):
        core_fr = _fold(_parts(fr)[1])
        core_en = _fold(_parts(en)[1])
        known = {
            "cidre": ("Vinaigre de cidre", "Apple cider vinegar"),
            "distille (blanc)": ("Vinaigre blanc", "White vinegar"),
            "balsamique": ("Vinaigre balsamique", "Balsamic vinegar"),
        }
        return known.get(core_fr, (f"Vinaigre de {_parts(fr)[1]}", f"{_parts(en)[1]} vinegar"))

    if group == "2":
        fr_parts = _parts(fr)[1:]
        en_parts = _parts(en)[1:]
        dried_fr = {
            "deshydrate": "séché",
            "deshydratee": "séchée",
            "deshydrates": "séchés",
            "deshydratees": "séchées",
        }
        fr_parts = [dried_fr.get(_fold(part), part) for part in fr_parts]
        if len(en_parts) >= 2 and _fold(en_parts[-1]) in {"dried", "ground"}:
            en_parts = [en_parts[-1].capitalize(), *en_parts[:-1]]
        elif len(en_parts) == 2 and _fold(en_parts[-1]) in {"black", "white"}:
            en_parts = [en_parts[-1].capitalize(), en_parts[0]]
        return _sentence(fr_parts), _sentence(en_parts)

    if group == "4":
        fr_parts = _parts(fr)
        en_parts = _parts(en)
        if fr_n.startswith("huile vegetale,"):
            core_fr = " ".join(fr_parts[1:])
            core_en = " ".join(en_parts[2:] if len(en_parts) > 2 and _fold(en_parts[1]) == "oil" else en_parts[1:])
            common_oils = {
                "olive": ("Huile d’olive", "Olive oil"),
                "arachide": ("Huile d’arachide", "Peanut oil"),
                "avocat": ("Huile d’avocat", "Avocado oil"),
                "amande": ("Huile d’amande", "Almond oil"),
            }
            return common_oils.get(_fold(core_fr), (f"Huile de {core_fr}", f"{core_en} oil"))
        animal_fr = [part for part in fr_parts[1:] if _fold(part) != "autochtone"]
        animal_en = [part for part in en_parts[1:] if _fold(part) != "indigenous"]
        if _fold(animal_fr[0]).startswith(("suif", "saindoux", "gras", "huile")):
            return _sentence(animal_fr), _sentence(animal_en)
        return _sentence(["Gras de", *animal_fr]), _sentence([*animal_en, "fat"])

    if group == "9":
        first_fr = re.sub(r"(?i)\s+cru(?:e|es|s)?$", "", _parts(fr)[0])
        first_en = re.sub(r"(?i)\s+raw$", "", _parts(en)[0])
        return _sentence([first_fr]), _sentence([first_en])

    if group == "11":
        frozen = bool(re.search(r"\b(?:congele|surgele)", fr_n))
        fr_parts = _clean_parts(fr, "fr", drop_prefix=False)
        en_parts = _clean_parts(en, "en", drop_prefix=False)
        if frozen:
            fr_parts.append("surgelé")
            en_parts.append("frozen")
        return _sentence(fr_parts), _sentence(en_parts)

    if group == "12":
        fr_parts = _clean_parts(fr, "fr")
        en_parts = _clean_parts(en, "en")
        if fr_n.startswith("graines,"):
            fr_parts = [part for part in fr_parts if _fold(part) != "graines"]
            en_parts = [part for part in en_parts if _fold(part) != "seeds"]
            return _sentence(["Graines de", *fr_parts]), _sentence(["Seeds of", *en_parts])
        return _sentence(fr_parts), _sentence(en_parts)

    if group == "16":
        fr_parts = _clean_parts(fr, "fr", drop_prefix=False)
        en_parts = _clean_parts(en, "en", drop_prefix=False)
        return _sentence([*fr_parts, "secs"]), _sentence([*en_parts, "dry"])

    if group == "20" and _fold(fr).startswith(("pates (spaghetti,", "pates, (spaghetti,")):
        return "Pâtes de blé entier", "Whole-wheat pasta"

    fr_parts = _clean_parts(fr, "fr")
    en_parts = _clean_parts(en, "en")
    if group == "20" and fr_parts and _fold(fr_parts[-1]) == "farine":
        fr_parts = ["Farine de", *fr_parts[:-1]]
    if group == "20" and en_parts and _fold(en_parts[-1]) == "flour":
        en_parts = [*en_parts[:-1], "flour"]
    name_fr, name_en = _sentence(fr_parts), _sentence(en_parts)
    if group == "20" and "farine à gâteau" in name_fr.casefold():
        return "Farine à gâteau", "Cake flour"
    return name_fr, name_en


def family_and_unit(row: dict, name_fr: str) -> tuple[str, str, str]:
    group = row["cnf_food_group_code"]
    normalized = normalize_label(name_fr)
    if group == "1":
        return "oeufs", "count", "unit"
    if group == "5":
        return "volaille", "mass", "g"
    if group == "10":
        return "porc", "mass", "g"
    if group == "13":
        return "boeuf", "mass", "g"
    if group == "2":
        return ("sauces", "volume", "ml") if normalized.startswith("vinaigre") else ("epices", "mass", "g")
    if group == "4":
        animal_fat = _fold(row["food_description_fr"]).startswith("gras animal,")
        liquid_oil = normalize_label(name_fr).startswith("huile ")
        mass = animal_fat and not liquid_oil
        return "huiles", ("mass" if mass else "volume"), ("g" if mass else "ml")
    if group == "9":
        return "fruits", "mass", "g"
    if group == "11":
        if any(word in normalized.split() for word in ("ail", "oignon", "poireau", "echalote")):
            return "alliums", "mass", "g"
        return "legumes", "mass", "g"
    if group == "12":
        return "noix_graines", "mass", "g"
    if group == "15":
        seafood = _fold(row["food_description_fr"]).startswith(("crustaces,", "mollusques,"))
        return ("fruits_de_mer" if seafood else "poissons"), "mass", "g"
    if group == "16":
        if normalize_label(name_fr).startswith(("pates ", "vermicelles ")):
            return "pates", "mass", "g"
        return "legumineuses", "mass", "g"
    if group == "20":
        if "riz" in normalized.split():
            return "riz", "mass", "g"
        if any(word in normalized for word in ("farine", "fecule", "amidon")):
            return "farines", "mass", "g"
        if any(word in normalized for word in ("pate", "nouille", "spaghetti", "macaroni")):
            return "pates", "mass", "g"
        return "cereales", "mass", "g"
    raise AssertionError(group)


def _slug(value: str) -> str:
    slug = normalize_label(value).replace(" ", "_")
    if slug[:1].isdigit():
        slug = f"ingredient_{slug}"
    return slug[:64].rstrip("_")


def _base_label_owners() -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    owners: dict[str, str] = {}
    labels: dict[str, tuple[str, str]] = {}
    for row in ingredient_rows():
        normalized = normalize_label(row["name"])
        owners[normalized] = row["id"]
        labels[f"fr:{normalized}"] = (row["id"], row["name"])
    for row in alias_rows():
        normalized = row["normalized_alias"]
        owners[normalized] = row["canonical_ingredient_id"]
        labels[f"{row['language']}:{normalized}"] = (
            row["canonical_ingredient_id"], row["alias"]
        )
    return owners, labels


def _similar_ids(labels: dict[str, tuple[str, str]], candidates: tuple[str, str]) -> list[str]:
    found: set[str] = set()
    for candidate in candidates:
        for owner, known_label in labels.values():
            if label_similarity(candidate, known_label) >= SIMILARITY_THRESHOLD:
                found.add(owner)
    return sorted(found)


def refine(rows: tuple[dict, ...], archive_sha256: str) -> dict:
    owners, known_labels = _base_label_owners()
    known_ids = {row["id"] for row in ingredient_rows()}
    reason_counts: Counter[str] = Counter()
    decisions: list[dict] = []
    review_samples: list[dict] = []

    for row in rows:
        reason = quality_reason(row)
        if reason is not None:
            reason_counts[reason] += 1
            continue

        name_fr, name_en = proposed_labels(row)
        normalized = (normalize_label(name_fr), normalize_label(name_en))
        if (
            not all(normalized)
            or max(len(name_fr), len(name_en)) > 120
            or min(len(normalized[0]), len(normalized[1])) < 3
        ):
            reason_counts["invalid_canonical_label"] += 1
            continue

        exact_ids = sorted({owners[label] for label in normalized if label in owners})
        if len(exact_ids) > 1:
            reason_counts["conflicting_exact_matches"] += 1
            review_samples.append({"food_code": row["food_code"], "name_fr": name_fr, "matches": exact_ids})
            continue

        snapshot = {
            "food_code": row["food_code"],
            "food_description_fr": row["food_description_fr"],
            "food_description_en": row["food_description_en"],
            "cnf_food_group_code": row["cnf_food_group_code"],
            "cnf_food_group_description_fr": row["cnf_food_group_description_fr"],
        }
        common = {
            "source_version": SOURCE_VERSION,
            "archive_sha256": archive_sha256,
            "food_code": row["food_code"],
            "reviewer": REVIEWER,
            "quality_checks": [
                "bilingual_identity",
                "ingredient_only_group",
                "simple_purchasable_state",
                "no_cooked_seasoned_or_composite_form",
                "canonical_label_within_limits",
            ],
            "candidate_snapshot": snapshot,
        }
        override = ATTACH_OVERRIDES.get(row["food_code"])
        if override is not None:
            if override not in known_ids:
                raise ValueError(f"Cible d'override inconnue : {override}")
            decisions.append({
                **common,
                "action": "attach_existing",
                "canonical_ingredient_id": override,
                "rationale": "Équivalence culinaire explicitement révisée malgré un ordre de mots FCÉN différent.",
                "aliases": [],
                "acknowledged_similar_ids": [],
            })
            reason_counts["accepted_attach_curated_override"] += 1
            continue
        if row["food_code"] in EXCLUDE_OVERRIDES:
            reason_counts["reviewed_similarity_excluded"] += 1
            continue
        if exact_ids:
            target = exact_ids[0]
            decisions.append({
                **common,
                "action": "attach_existing",
                "canonical_ingredient_id": target,
                "rationale": "Correspondance exacte avec un nom ou alias déjà approuvé; aucun nouveau canon créé.",
                "aliases": [],
                "acknowledged_similar_ids": [],
            })
            reason_counts["accepted_attach_exact"] += 1
            continue

        similar = _similar_ids(known_labels, (name_fr, name_en))
        ingredient_id = _slug(name_fr)
        if ingredient_id in known_ids:
            reason_counts["slug_collision_requires_review"] += 1
            continue
        family_id, unit_kind, base_unit = family_and_unit(row, name_fr)
        canonical = {
            "id": ingredient_id,
            "family_id": family_id,
            "name": name_fr,
            "unit_kind": unit_kind,
            "base_unit": base_unit,
            "perishability": None,
            "salvage_value_cents_per_base_unit": None,
            "density_g_per_ml": None,
        }
        decisions.append({
            **common,
            "action": "create_variant",
            "canonical_ingredient_id": None,
            "canonical": canonical,
            "rationale": (
                "Aliment simple dans un état achetable explicite; les identifiants "
                "similaires ont été revus et désignent une variété, une espèce ou "
                "un état distinct."
                if similar else
                "Aliment simple dans un état achetable explicite; identité bilingue "
                "distincte sans collision exacte ou similaire."
            ),
            "aliases": [{"language": "en", "alias": name_en}],
            "acknowledged_similar_ids": similar,
        })
        reason_counts[
            "accepted_create_reviewed_similar" if similar
            else "accepted_create_variant"
        ] += 1
        known_ids.add(ingredient_id)
        for language, label in (("fr", name_fr), ("en", name_en)):
            label_n = normalize_label(label)
            owners[label_n] = ingredient_id
            known_labels[f"{language}:{label_n}"] = (ingredient_id, label)

    return {
        "source": "cnf",
        "source_version": SOURCE_VERSION,
        "archive_sha256": archive_sha256,
        "rules_version": RULES_VERSION,
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "allowed_group_codes": sorted(ALLOWED_GROUPS, key=int),
        "source_row_count": len(rows),
        "reason_counts": dict(sorted(reason_counts.items())),
        "decisions": decisions,
        "review_samples": review_samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "seed" / "main" / "cnf_catalog_curation.json",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    parsed = parse_cnf_archive(args.archive, source_version=SOURCE_VERSION)
    result = refine(parsed.rows, parsed.archive_sha256)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if not args.dry_run:
        args.output.write_text(encoded, encoding="utf-8")
    print(json.dumps({
        "archive_sha256": result["archive_sha256"],
        "source_row_count": result["source_row_count"],
        "decision_count": len(result["decisions"]),
        "reason_counts": result["reason_counts"],
        "output": None if args.dry_run else str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
