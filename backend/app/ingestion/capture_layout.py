"""Découverte des dossiers de pages d'une capture, quelle que soit sa disposition.

Une semaine de capture contient à la fois des dossiers de catégories à plat et
des exécutions isolées ``run-<horodatage>/<catégorie>/``. Les deux sont des
preuves de la même semaine chez la même bannière : en ignorer une laisse une
capture plus récente et plus riche hors de la mesure de couverture, sans que
rien ne le signale. La déduplication d'un même produit vu dans plusieurs
dossiers reste la responsabilité de l'adaptateur, qui conserve l'observation la
plus riche et la preuve promotionnelle.

Le module est volontairement pur : ni base de données, ni réseau.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

MANIFEST_PREFIX = "_"


def is_capture_page(path: Path) -> bool:
    """Un fichier de pages, par opposition à un manifeste ``_complete.json``."""
    return (
        path.is_file()
        and path.suffix == ".json"
        and not path.name.startswith(MANIFEST_PREFIX)
    )


def capture_page_dirs(root: str | Path) -> tuple[Path, ...]:
    """Tous les dossiers contenant des pages sous ``root``, exécutions incluses."""
    resolved = Path(root).resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"Répertoire de capture introuvable: {resolved}")
    directories = sorted(
        {path.parent for path in resolved.rglob("*.json") if is_capture_page(path)}
    )
    if not directories:
        raise FileNotFoundError(f"Aucune page de capture sous {resolved}")
    return tuple(directories)


def capture_page_dirs_many(roots: Iterable[str | Path]) -> tuple[Path, ...]:
    """Union ordonnée et sans doublon des dossiers de plusieurs racines."""
    found: dict[Path, None] = {}
    for root in roots:
        for directory in capture_page_dirs(root):
            found[directory] = None
    return tuple(sorted(found))
