"""Charger la page d'une recette — la seule partie qui touche le réseau.

Pourquoi un port. La règle d'architecture du projet veut que l'acquisition vive
ici, jamais dans une requête HTTP servie par l'API : une page lente ou un site
en panne ne doit pas faire attendre l'application (D28 l'a déjà tranché pour le
rafraîchissement des prix, qui est un lot lancé, jamais attendu). Les tests
n'ont donc pas besoin du réseau : ils passent un port de gabarit.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Protocol

__all__ = ["FixtureRecipePage", "RecipePagePort", "UrlRecipePage"]

#: Un en-tête d'agent honnête : le site voit qui l'appelle, et pourquoi.
_USER_AGENT = "Souschef/1.0 (import de recette déclenché par l'usager)"


class RecipePagePort(Protocol):
    def fetch(self, url: str) -> bytes:
        """Les octets de la page, ou une exception."""
        ...


class UrlRecipePage:
    """Le port réel : une requête HTTP, un délai borné."""

    def __init__(self, timeout_s: int = 30) -> None:
        self._timeout_s = timeout_s

    def fetch(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
            return response.read()


class FixtureRecipePage:
    """Le port des tests et des rejeux : une page déjà enregistrée."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def fetch(self, url: str) -> bytes:
        del url
        return self._path.read_bytes()
