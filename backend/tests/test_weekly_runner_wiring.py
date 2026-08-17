"""L'import hebdomadaire applique les mêmes règles que le rapport.

Le runner hebdomadaire est le seul chemin qui écrit dans `market.product` /
`market.price`. Il construisait ses deux adaptateurs sans `identity_rules` ni
`tax_schedule`, que le rapport hors ligne leur passe pourtant : toutes les
gardes d'identité — produit composé, format de gros, rayon réservé — étaient
inertes sur les données qui atteignent la base, et le vin comme la bière y
entraient détaxés. Le catalogue persisté et les devis publiés étaient calculés
sous deux régimes différents.

Aucun test Python ne pouvait attraper ça : les deux appelants sont corrects
isolément, c'est leur divergence qui est le défaut. La garde vit donc sur le
câblage lui-même.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "run_weekly_catalogues.py"
QUOTES = REPO_ROOT / "scripts" / "quote_recipes.py"

#: Ce qu'un adaptateur doit recevoir pour appliquer toutes les règles curées.
REQUIRED_GUARDS = ("product_conversions", "identity_rules", "tax_schedule")


def _adapter_calls(source: Path) -> dict[str, set[str]]:
    """Mots-clés passés à chaque construction d'adaptateur de capture."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id in {"MaxiCaptureAdapter", "SuperCCaptureAdapter"}:
            found[node.func.id] = {kw.arg for kw in node.keywords if kw.arg}
    return found


@pytest.mark.parametrize("source", [RUNNER, QUOTES], ids=["runner", "rapport"])
def test_both_paths_arm_every_curation_guard(source: Path):
    calls = _adapter_calls(source)
    assert calls, f"Aucun adaptateur construit dans {source.name}"
    for adapter, keywords in calls.items():
        missing = sorted(set(REQUIRED_GUARDS) - keywords)
        assert not missing, (
            f"{source.name}: {adapter} construit sans {missing}. "
            "Les règles de curation ne s'appliqueraient pas sur ce chemin."
        )


def test_the_runner_and_the_report_arm_the_same_guards():
    """La divergence entre les deux chemins est le défaut, pas leur contenu."""
    runner = _adapter_calls(RUNNER)
    report = _adapter_calls(QUOTES)
    for adapter in sorted(set(runner) & set(report)):
        assert set(REQUIRED_GUARDS) <= runner[adapter], adapter
        assert set(REQUIRED_GUARDS) <= report[adapter], adapter


def test_the_runner_configuration_declares_where_those_rules_live():
    config_path = REPO_ROOT / "config" / "catalogues.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    for key in ("procurement_rules", "identity_rules", "tax_rates"):
        value = config.get(key)
        assert value, f"config/catalogues.json n'a pas de clé {key!r}"
        assert (config_path.parent / value).is_file(), f"{key} -> {value} introuvable"
