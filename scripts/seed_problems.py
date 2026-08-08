#!/usr/bin/env python3
"""Seed the 50 master problems into PostgreSQL from the bundled seed file.

Idempotent: matches on slug, updating existing rows rather than duplicating.
Preserves any authored hidden_tests already in the database unless the seed
file supplies its own.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Problem  # noqa: E402

DEFAULT = Path(__file__).resolve().parent / "seed_data.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(DEFAULT))
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        raise SystemExit(
            f"seed file not found: {path}\n"
            "Run scripts/export_seed_data.py to regenerate it from the "
            "Phase 1 corpus."
        )

    bundle = json.loads(path.read_text())
    created = updated = 0

    with SessionLocal() as db:
        for item in bundle:
            existing = db.scalar(select(Problem).where(Problem.slug == item["slug"]))
            if existing:
                for k, v in item.items():
                    if k == "slug":
                        continue
                    # don't clobber authored hidden tests with an empty list
                    if k == "hidden_tests" and not v and existing.hidden_tests:
                        continue
                    setattr(existing, k, v)
                updated += 1
            else:
                db.add(Problem(**item))
                created += 1
        db.commit()

    print(f"created: {created}  updated: {updated}  total: {len(bundle)}")


if __name__ == "__main__":
    main()
