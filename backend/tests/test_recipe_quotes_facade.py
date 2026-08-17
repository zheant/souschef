"""Tests de la façade SQL du calcul de prix.

Elle n'en avait aucun : le filtre de date, le filtre magasin, la fusion des
niveaux de confiance et surtout la localisation du fichier de règles n'étaient
exercés nulle part. C'est ce dernier trou qui a laissé passer une route
répondant 500 dans la pile livrée — le chemin des règles pointait hors de
l'image, et rien ne pouvait le faire échouer en test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import recipe_quotes


def test_rules_path_follows_the_configured_directory(monkeypatch):
    monkeypatch.setattr(recipe_quotes.settings, "config_dir", "/quelque/part")
    assert recipe_quotes.rules_path() == Path(
        "/quelque/part/ingredient-procurement-rules.json"
    )


def test_a_missing_rules_file_is_named_not_a_raw_oserror(tmp_path, monkeypatch):
    monkeypatch.setattr(recipe_quotes.settings, "config_dir", str(tmp_path))
    recipe_quotes._load_supply_rules_cached.cache_clear()
    with pytest.raises(recipe_quotes.ProcurementRulesUnavailable) as error:
        recipe_quotes._load_supply_rules()
    assert "MENU_CONFIG_DIR" in str(error.value)


def test_an_unreadable_rules_file_is_named_too(tmp_path, monkeypatch):
    (tmp_path / "ingredient-procurement-rules.json").write_text("{ pas du json", encoding="utf-8")
    monkeypatch.setattr(recipe_quotes.settings, "config_dir", str(tmp_path))
    recipe_quotes._load_supply_rules_cached.cache_clear()
    with pytest.raises(recipe_quotes.ProcurementRulesUnavailable):
        recipe_quotes._load_supply_rules()


def test_rules_are_read_once_not_per_request(tmp_path, monkeypatch):
    path = tmp_path / "ingredient-procurement-rules.json"
    path.write_text(
        json.dumps({"supply_rules": [{"ingredient_id": "eau", "kind": "essential"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(recipe_quotes.settings, "config_dir", str(tmp_path))
    recipe_quotes._load_supply_rules_cached.cache_clear()

    first = recipe_quotes._load_supply_rules()
    path.unlink()  # le fichier disparaît: un second chargement échouerait
    second = recipe_quotes._load_supply_rules()

    assert first == second
    assert [rule.ingredient_id for rule in first] == ["eau"]


def test_the_shipped_configuration_directory_actually_holds_the_rules():
    """Le défaut de configuration doit fonctionner depuis le dépôt.

    Ce test échoue si le dossier de configuration cesse d'être versionné — la
    situation exacte dans laquelle la route était livrée cassée.
    """
    repo_root = Path(__file__).resolve().parents[2]
    shipped = repo_root / "config" / "ingredient-procurement-rules.json"
    assert shipped.is_file(), (
        "config/ingredient-procurement-rules.json doit être versionné: la route "
        "des devis ne peut pas fonctionner sans lui."
    )
    payload = json.loads(shipped.read_text(encoding="utf-8"))
    rules = recipe_quotes._parse_supply_rules(payload)
    assert rules, "Le fichier livré doit contenir au moins une règle."
    assert any(rule.kind == "essential" for rule in rules)


def test_the_compose_stack_puts_the_rules_where_the_api_looks():
    """La panne était un défaut de déploiement, donc la garde vit là aussi.

    L'image ne copie que `backend/`; le dossier de configuration doit être monté
    et l'emplacement annoncé au service par la variable d'environnement. Un test
    qui n'exerce que le code Python n'aurait jamais pu attraper ça — c'est
    exactement la leçon consignée dans CLAUDE.md sur les chemins que la
    documentation décrit mais que personne ne fait échouer exprès.
    """
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "MENU_CONFIG_DIR: /config" in compose
    assert "./config:/config:ro" in compose
