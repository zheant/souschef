"""Les modules de calcul purs restent importables sans SQLAlchemy.

Leur docstring l'affirme (« ne connaît ni SQLAlchemy ni HTTP ») et l'ADR de
sémantique des prix en fait une promesse produit : « les rapports hebdomadaires
peuvent donc comparer la couverture sans PostgreSQL ». Une affirmation qu'aucun
test ne peut faire échouer n'est pas une garantie — celui-ci l'exerce vraiment,
dans un interpréteur où l'import de SQLAlchemy est refusé.

Le calcul nutritionnel hérite de la même promesse : son audit de couverture
tourne sur le seed, le règlement versionné et l'archive fédérale, sans base.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]

#: Modules qui doivent rester purs. Le module de coût et celui de vraisemblance
#: servent aussi les scripts hors ligne, qui tournent sans base.
PURE_MODULES = (
    "app.services.confidence",
    "app.services.recipe_costing",
    "app.services.recipe_quality",
    "app.services.recipe_pricing_coverage",
    "app.services.recipe_scaling",
    "app.services.nutrition_rules",
    "app.services.recipe_nutrition",
    "app.services.recipe_nutrition_coverage",
    "app.services.cnf_match_proposal",
    "app.services.fcen_measures",
)


def _import_without_sqlalchemy(module_names: tuple[str, ...]) -> subprocess.CompletedProcess:
    program = textwrap.dedent(
        f"""
        import importlib, sys

        class Refuse:
            def find_module(self, name, path=None):
                return self.find_spec(name, path)

            def find_spec(self, name, path=None, target=None):
                root = name.split(".", 1)[0]
                if root in {{"sqlalchemy", "psycopg2", "fastapi", "pulp"}}:
                    raise ImportError(f"import refusé pour le test: {{name}}")
                return None

        sys.meta_path.insert(0, Refuse())
        for name in {module_names!r}:
            importlib.import_module(name)
        print("ok")
        """
    )
    # Encodage imposé des deux côtés : sous Windows, un enfant Python écrit
    # dans la page de codes de la console, et « refusé » revenait « refusÃ© »
    # au parent — le piège mordait, seule l'assertion sur son message échouait.
    # Même correctif que D28 pour le journal du collecteur.
    return subprocess.run(
        [sys.executable, "-c", program],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )


def test_pure_modules_import_without_sqlalchemy():
    result = _import_without_sqlalchemy(PURE_MODULES)
    assert result.returncode == 0, (
        "Un import transitif vers la couche base de données est revenu:\n"
        f"{result.stderr}"
    )
    assert result.stdout.strip() == "ok"


def test_the_guard_itself_bites():
    """Le piège doit réellement refuser SQLAlchemy, sinon il ne prouve rien."""
    result = _import_without_sqlalchemy(("sqlalchemy",))
    assert result.returncode != 0
    assert "import refusé pour le test" in result.stderr


def test_database_bound_services_are_still_reachable():
    """La pureté ne doit pas se payer en cassant les appelants existants."""
    from app import services

    assert services.validate_problem is not None
    assert services.load_problem_data is not None
    assert services.RuleBasedAppetenceScorer is not None
    assert "convert_qty" in services.__all__
