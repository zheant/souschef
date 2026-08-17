"""Adaptation des captures Super C au contrat natif de Souschef."""

from __future__ import annotations

from ..adapters.maxi_capture import MaxiCaptureAdapter, MaxiMatchDecision


SuperCMatchDecision = MaxiMatchDecision


class SuperCCaptureAdapter(MaxiCaptureAdapter):
    """Même rapprochement canonique que Maxi, avec des identifiants Super C."""

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            **kwargs,
            source_name="Super C",
            source_prefix="superc",
        )
