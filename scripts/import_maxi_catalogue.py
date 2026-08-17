"""Prévisualiser ou importer des captures Maxi dans Souschef.

Exécuter depuis la racine du dépôt. Sans ``--apply``, aucune base n'est
modifiée et un rapport de rapprochement est affiché.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.adapters.maxi_capture import (
    MaxiCaptureAdapter,
    load_match_overrides,
    load_title_overrides,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", action="append", required=True)
    parser.add_argument("--seed-dir", default=str(ROOT / "seed" / "main"))
    parser.add_argument("--store-external-key", required=True)
    parser.add_argument("--week", required=True)
    parser.add_argument("--valid-from", type=date.fromisoformat, required=True)
    parser.add_argument("--valid-to", type=date.fromisoformat, required=True)
    parser.add_argument("--overrides")
    parser.add_argument("--title-overrides")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    adapter = MaxiCaptureAdapter(
        args.capture_dir,
        args.seed_dir,
        store_external_key=args.store_external_key,
        week=args.week,
        valid_from=args.valid_from,
        valid_to=args.valid_to,
        overrides=load_match_overrides(args.overrides),
        title_overrides=load_title_overrides(args.title_overrides),
    )
    payload = {
        "summary": adapter.report(),
        "decisions": [decision.as_dict() for decision in adapter.decisions],
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    result = dict(payload["summary"])
    if args.apply:
        from app.db import SessionLocal
        from app.ingestion.maxi import import_maxi_catalogue

        with SessionLocal.begin() as session:
            result["database"] = import_maxi_catalogue(session, adapter)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
