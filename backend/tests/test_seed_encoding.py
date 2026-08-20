"""Les fichiers de seed se lisent en UTF-8, quelle que soit la machine.

Les jeux de seed sont versionnés en UTF-8 et portent des accents partout
(« Échalote française », « Œuf de calibre gros », « Crème 35 % »). Les
chargeurs les lisaient sans préciser d'encodage : `Path.read_text()` retombe
alors sur `locale.getpreferredencoding(False)`, soit **cp1252** sur une machine
Windows francophone. Le conteneur Docker tournant en UTF-8, le défaut restait
invisible sur le chemin documenté et n'apparaissait qu'en développement local —
où il a écrit « Å'uf de calibre gros » dans PostgreSQL, puis à l'écran.

Deux gardes, parce qu'un seul ne suffirait pas :

- le premier exerce les chargeurs sous `-X warn_default_encoding`, qui
  transforme toute lecture sans encodage explicite en `EncodingWarning`. Il
  mord sur la classe de défaut entière, pas sur les sept points d'appel connus ;
- le second vérifie le résultat : les accents traversent le chargement intacts.
  Le premier garde passerait encore si quelqu'un écrivait `encoding="cp1252"`.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
SEED_DIR = BACKEND.parent / "seed" / "main"

#: Chaînes présentes dans `seed/main/canonical_ingredients.json`, choisies pour
#: couvrir trois pièges distincts : ligature (Œ), accent aigu et cédille.
ACCENTED_SAMPLES = ("Œuf de calibre gros", "Échalote française")


def _run_with_encoding_guard(program: str) -> subprocess.CompletedProcess:
    """Exécute `program` avec toute lecture sans encodage promue en erreur."""
    return subprocess.run(
        [
            sys.executable,
            "-X",
            "warn_default_encoding",
            "-W",
            "error::EncodingWarning",
            "-c",
            textwrap.dedent(program),
        ],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_seed_loaders_never_rely_on_the_platform_encoding():
    result = _run_with_encoding_guard(
        f"""
        from pathlib import Path

        from app.adapters.json_circular import JsonCircularAdapter
        from app.adapters.json_recipe_source import JsonRecipeSourceAdapter
        from app.seeding.seed import _load, _load_optional

        seed_dir = Path({str(SEED_DIR)!r})

        _load(seed_dir, "canonical_ingredients.json")
        _load(seed_dir, "household.json")
        _load_optional(seed_dir, "products.json")

        circular = JsonCircularAdapter(seed_dir)
        circular.all_weeks()
        circular.all_store_keys()
        circular.fetch_week(circular.all_store_keys()[0], circular.all_weeks()[0])

        JsonRecipeSourceAdapter(seed_dir).load_all()
        print("ok")
        """
    )
    assert result.returncode == 0, (
        "Une lecture de seed est repartie sur l'encodage de la plateforme:\n"
        f"{result.stderr}"
    )
    assert result.stdout.strip() == "ok"


def test_the_guard_itself_bites():
    """Sans le garde, le test précédent ne prouverait rien."""
    result = _run_with_encoding_guard(
        """
        from pathlib import Path
        Path(__file__ if False else "pyproject.toml").read_text()
        print("ok")
        """
    )
    assert result.returncode != 0
    assert "EncodingWarning" in result.stderr


def test_accents_survive_the_load():
    """L'encodage explicite ne vaut que s'il est le bon."""
    from app.seeding.seed import _load

    names = {row["name"] for row in _load(SEED_DIR, "canonical_ingredients.json")}
    missing = [sample for sample in ACCENTED_SAMPLES if sample not in names]
    assert not missing, f"Accents perdus au chargement du seed: {missing}"
