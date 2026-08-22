"""La commande d'import par URL propose, et refuse d'écrire sans confirmation.

C'est la seule propriété de sécurité de ce chemin : une ressemblance ne doit
jamais devenir une recette de la base sans qu'un humain l'ait dit.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "import_recipe_from_url.py"
)
SPEC = importlib.util.spec_from_file_location("import_recipe_from_url", SCRIPT)
url_import = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = url_import
SPEC.loader.exec_module(url_import)


def _review(**overrides):
    review = {
        "source_url": "https://exemple.ca/recettes/x",
        "name": "Recette d'essai",
        "servings": 4,
        "prep_time_h": "0.25",
        "lines": [
            {
                "original_ingredient_line": "Macaroni, 340 g",
                "proposed_canonical_ingredient_id": "macaroni",
                "converted_base_quantity": "340",
                "confirmed": True,
                "blockers": [],
            }
        ],
    }
    review.update(overrides)
    return review


def test_a_confirmed_review_becomes_a_recipe_at_the_seed_contract():
    recipe = url_import.build_recipe(_review())
    assert recipe["name"] == "Recette d'essai"
    assert recipe["original_servings"] == 4
    assert recipe["tags"]["source_url"].endswith("/x")
    assert recipe["ingredients"] == [
        {
            "canonical_ingredient_id": "macaroni",
            "qty_fixed_per_batch_base_unit": "340",
            "qty_marginal_per_serving_base_unit": "0",
            "substitutable": False,
        }
    ]


def test_an_unconfirmed_line_refuses_the_whole_recipe():
    lines = _review()["lines"]
    lines[0]["confirmed"] = False
    with pytest.raises(SystemExit) as error:
        url_import.build_recipe(_review(lines=lines))
    assert "non confirmée" in str(error.value)


def test_a_blocked_line_refuses_even_when_someone_confirmed_it():
    """Confirmer ne lève pas un blocage : la quantité manque toujours."""
    lines = _review()["lines"]
    lines[0]["blockers"] = ["aucune quantité lisible"]
    with pytest.raises(SystemExit):
        url_import.build_recipe(_review(lines=lines))


def test_a_page_without_a_published_yield_refuses():
    """Sans rendement, la mise à l'échelle n'a pas de point de départ."""
    with pytest.raises(SystemExit) as error:
        url_import.build_recipe(_review(servings=None))
    assert "rendement" in str(error.value)
