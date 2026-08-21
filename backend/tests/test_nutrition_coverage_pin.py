"""La couverture nutritionnelle atteinte est verrouillée, pas racontée.

Le chiffre vit dans un test parce qu'une modification de seed, de règlement ou
de recette peut l'éroder sans lever d'exception : les recettes qui cessent
d'être calculables redeviennent simplement « incomplètes », et personne ne le
voit avant de relancer l'audit à la main.

Le test lit l'archive fédérale livrée dans ``data/`` — la même que l'audit — et
se saute si elle n'est pas là (un poste qui n'a pas téléchargé les 25 Mo n'a
pas à échouer pour ça).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
ARCHIVE = ROOT / "data" / "cnf_fcen_all-files-data_2026.zip"
RULES = ROOT / "config" / "nutrition-rules.json"
SEED_MAIN = ROOT / "seed" / "main"
UNIT_CURATION = ROOT / "config" / "cook_recipe_curation.json"

#: Recettes calculables sur le corpus livré, règlement 2026-08-21d. Descendre
#: ce plancher est une décision, pas un effet de bord : le baisser demande de
#: dire quelle recette a cessé d'être calculable, et pourquoi.
MINIMUM_COMPLETE_RECIPES = 113

#: Ingrédients encore bloquants, et la raison de chacun. Le total est borné
#: plutôt que fixé : curer en fait baisser le nombre, ce qui doit passer.
MAXIMUM_BLOCKING_INGREDIENTS = 8

#: L'archive est ignorée par git (25 Mo), donc absente d'un clone neuf : le
#: saut par défaut évite de faire échouer un poste qui ne l'a pas téléchargée.
#: Mais un saut silencieux fait passer au vert exactement l'érosion que cette
#: épingle existe pour attraper. `MENU_REQUIRE_NUTRITION_ARCHIVE=1` transforme
#: le saut en échec : c'est ce que doit poser une intégration continue.
_REQUIRED = os.environ.get("MENU_REQUIRE_NUTRITION_ARCHIVE") == "1"

if not ARCHIVE.exists() and _REQUIRED:
    pytest.fail(
        f"MENU_REQUIRE_NUTRITION_ARCHIVE=1 mais {ARCHIVE} est absente : "
        "l'épingle de couverture ne peut pas s'exercer.",
        pytrace=False,
    )

pytestmark = pytest.mark.skipif(
    not ARCHIVE.exists(),
    reason=(
        "archive FCÉN absente de data/ — poser "
        "MENU_REQUIRE_NUTRITION_ARCHIVE=1 pour en faire un échec"
    ),
)


@pytest.fixture(scope="module")
def audit():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    from app.services.nutrition_rules import parse_nutrition_rules
    from app.services.recipe_nutrition_coverage import (
        audit_recipe_nutrition_coverage,
    )
    from nutrition_inputs import load_foods, load_ingredients, load_recipes

    rules = parse_nutrition_rules(json.loads(RULES.read_text(encoding="utf-8")))
    return audit_recipe_nutrition_coverage(
        load_recipes(SEED_MAIN),
        load_ingredients(SEED_MAIN, UNIT_CURATION),
        load_foods(ARCHIVE),
        rules,
    )


def test_the_coverage_floor_holds(audit):
    assert audit.complete_recipes >= MINIMUM_COMPLETE_RECIPES, (
        f"{audit.complete_recipes}/{audit.total_recipes} recettes calculables, "
        f"contre {MINIMUM_COMPLETE_RECIPES} verrouillées."
    )
    assert audit.blocking_ingredients <= MAXIMUM_BLOCKING_INGREDIENTS


def test_every_remaining_gap_names_a_reason_the_module_publishes(audit):
    """Aucun trou muet : chaque bloquant restant porte une raison connue.

    Les huit qui restent sont des trous du fichier fédéral, pas de la
    curation :

    - aucun aliment publié : pâte brisée, pâte de cari vert thaï, gnocchis frais;
    - aucune mesure de compte : feuille de riz;
    - des mesures de compte dont aucune ne nomme l'ingrédient : pain à
      sous-marin, dont l'aliment ne publie que des tranches de pain italien
      (35 g). La dérivation les proposait avant qu'elle refuse ce cas — 35 g
      pour une pièce d'environ 85 g, qu'un curateur pouvait recopier de bonne
      foi;
    - une seule mesure de volume, qui décrit un solide en dés : feuillage de
      fenouil, aubergine grillée, jus de cornichon. Leur canon se mesure au
      millilitre alors que la recette manipule un solide, et 0,37 g/ml n'est
      pas une densité.
    """
    from app.services.recipe_nutrition import (
        AMBIGUOUS_CNF_FOOD,
        CHOSEN_FOOD_ALREADY_ATTACHED,
        CHOSEN_FOOD_NOT_ATTACHED,
        MISSING_DENSITY,
        MISSING_GRAMS_PER_UNIT,
        MISSING_NUTRIENT_VALUES,
        NO_CNF_FOOD,
        OVER_NEGLIGIBLE_CEILING,
        UNKNOWN_INGREDIENT,
    )

    known = {
        NO_CNF_FOOD,
        AMBIGUOUS_CNF_FOOD,
        CHOSEN_FOOD_NOT_ATTACHED,
        CHOSEN_FOOD_ALREADY_ATTACHED,
        MISSING_DENSITY,
        MISSING_GRAMS_PER_UNIT,
        MISSING_NUTRIENT_VALUES,
        OVER_NEGLIGIBLE_CEILING,
        UNKNOWN_INGREDIENT,
    }
    reasons = {gap.reason for gap in audit.gaps}
    assert reasons <= known, reasons - known
    # Deux raisons doivent avoir disparu : elles disaient qu'un appariement
    # manquait là où le règlement en déclare un.
    assert CHOSEN_FOOD_NOT_ATTACHED not in reasons
    assert CHOSEN_FOOD_ALREADY_ATTACHED not in reasons
