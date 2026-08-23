#!/usr/bin/env python3
"""Inventory and safely relocate canonical tasks using explicit JSON mappings.

Dry-run is the default. Applying requires --apply, --backup-dir, and an explicit
journal directory; no production wiki should be passed without a separate gate.
"""

from __future__ import annotations

import argparse
import json

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.task_relocation import (
    inventory_task_ownership,
    load_relocation_mappings,
    recover_relocations,
    relocate_tasks,
)
from lifeos.wiki_store import WikiRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="sqlite:///./data/lifeos.db")
    parser.add_argument("--wiki-root", default="/wiki")
    parser.add_argument(
        "--mapping", help="JSON list (or {mappings: [...]}) with exact source and owner IDs, paths, and source hash"
    )
    parser.add_argument("--journal-dir", default="./data/task-relocation-journal")
    parser.add_argument("--backup-dir", help="required with --apply; per-source backup destination")
    parser.add_argument("--backup-evidence", help="verified normal wiki and SQLite backup evidence for this target")
    parser.add_argument("--apply", action="store_true", help="perform a journaled relocation after preflight")
    parser.add_argument(
        "--recover", action="store_true", help="reconcile unfinished journals without accepting new mappings"
    )
    args = parser.parse_args()
    if args.apply and not args.mapping:
        parser.error("--apply requires --mapping")
    if args.apply and not args.backup_dir:
        parser.error("--apply requires --backup-dir")
    if (args.apply or args.recover) and not args.backup_evidence:
        parser.error("--apply/--recover requires --backup-evidence")
    if args.recover and args.mapping:
        parser.error("--recover does not accept --mapping")

    engine = create_engine(args.database)
    initialize_database(engine)
    factory = create_session_factory(engine)
    repository = WikiRepository(args.wiki_root)
    with factory() as session:
        if args.recover:
            result = {
                "recovered": recover_relocations(
                    session,
                    repository,
                    journal_dir=args.journal_dir,
                    backup_evidence=args.backup_evidence,
                    database_target=args.database,
                )
            }
        elif args.mapping:
            result = relocate_tasks(
                session,
                repository,
                load_relocation_mappings(args.mapping),
                journal_dir=args.journal_dir,
                apply=args.apply,
                backup_dir=args.backup_dir,
                backup_evidence=args.backup_evidence,
                database_target=args.database,
            )
        else:
            result = inventory_task_ownership(repository)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
