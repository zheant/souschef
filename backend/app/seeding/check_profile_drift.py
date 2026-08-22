"""Garde contre la dérive de ``household_profile`` en base par rapport au
seed versionné (D16, docs/deviations.md).

La base de dev peut diverger du seed — édition manuelle via l'écran Ménage,
exploration au clavier, ancien conteneur jamais réensemencé — sans que rien
ne le signale : une session de vérification qui tourne contre une base
dérivée teste un profil différent de celui documenté dans
``docs/calibration.md``. C'était exactement le cas trouvé le 2026-08-10 :
``min_distinct_recipes`` valait 7 en base contre 4 dans
``seed/main/household.json``.

À exécuter en DÉBUT de toute session de vérification (voir CLAUDE.md).

Usage : ``python -m app.seeding.check_profile_drift [--seed-dir seed/main] [--profile-id default]``
Sortie : liste les champs qui diffèrent ; code de sortie 1 si dérive
détectée, 0 sinon (0 aussi si le profil n'existe pas encore en base — rien
n'a eu l'occasion de dériver).
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from ..db import SessionLocal
from ..models import HouseholdProfile

#: Champs Decimal en base — comparaison via Decimal(str(...)) pour éviter les
#: faux positifs de représentation flottante (ex. 0.3 JSON vs Decimal("0.300")).
_DECIMAL_FIELDS = {
    "home_lat", "home_lng", "demand_slack_epsilon",
    "max_share_per_recipe", "max_prep_time_per_meal_h",
}


def _normalize(key: str, value):
    if value is None:
        return None
    if key in _DECIMAL_FIELDS:
        return Decimal(str(value))
    return value


def check(
    seed_dir: str, profile_id: str = "default", session_factory=SessionLocal
) -> list[tuple[str, object, object]]:
    """Retourne la liste des (champ, valeur_seed, valeur_base) qui diffèrent.

    Liste vide : aucune dérive (ou profil absent des deux côtés)."""
    seed_profile = json.loads(
        (Path(seed_dir) / "household.json").read_text(encoding="utf-8")
    )["profile"]

    with session_factory() as session:
        db_profile = session.get(HouseholdProfile, profile_id)

    if db_profile is None:
        return []  # rien en base : pas de dérive possible, seul le seeding s'applique

    drift = []
    for key, seed_value in seed_profile.items():
        if key == "id":
            continue
        db_value = getattr(db_profile, key, None)
        if _normalize(key, seed_value) != _normalize(key, db_value):
            drift.append((key, seed_value, db_value))
    return drift


def run(
    seed_dir: str, profile_id: str = "default", session_factory=SessionLocal
) -> bool:
    """Affiche le résultat ; retourne True si conforme (ou absent), False si dérive."""
    drift = check(seed_dir, profile_id, session_factory)
    if not drift:
        print(
            f"household_profile '{profile_id}' conforme à "
            f"{seed_dir}/household.json (ou absent de la base)."
        )
        return True
    print(
        f"DÉRIVE DÉTECTÉE — household_profile '{profile_id}' ≠ "
        f"{seed_dir}/household.json :"
    )
    for key, seed_value, db_value in drift:
        print(f"  {key}: seed={seed_value!r}  base={db_value!r}")
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-dir", default=None)
    parser.add_argument("--profile-id", default="default")
    args = parser.parse_args()
    from ..config import settings

    ok = run(args.seed_dir or settings.seed_dir, args.profile_id)
    sys.exit(0 if ok else 1)
