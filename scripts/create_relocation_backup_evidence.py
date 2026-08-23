#!/usr/bin/env python3
"""Create verified normal-backup evidence for a planned task relocation."""

from __future__ import annotations

import argparse
from pathlib import Path

from lifeos.task_relocation import create_verified_backup_evidence
from lifeos.wiki_store import WikiRepository


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--database-target", required=True, help="exact database URL supplied to relocate_wiki_tasks.py"
    )
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--wiki-backup", type=Path, required=True)
    parser.add_argument("--sqlite-backup", type=Path, required=True)
    args = parser.parse_args()
    result = create_verified_backup_evidence(
        WikiRepository(args.wiki_root),
        database=args.database,
        database_target=args.database_target,
        evidence_path=args.evidence,
        wiki_backup_path=args.wiki_backup,
        sqlite_backup_path=args.sqlite_backup,
    )
    print(f"evidence={result}")


if __name__ == "__main__":
    main()
