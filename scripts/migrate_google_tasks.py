#!/usr/bin/env python3
"""Create a deterministic, offline Google Tasks migration report or staging import."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from lifeos.google_tasks_migration import import_to_database, load_export, select_for_migration, to_lifeos_record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="combined read-only Google Tasks export JSON")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--records-out", type=Path)
    parser.add_argument("--staging-database", type=Path)
    parser.add_argument("--wiki-root", type=Path)
    args = parser.parse_args()
    records = load_export(args.export)
    selected, excluded = select_for_migration(records, args.as_of)
    mapped = [to_lifeos_record(record) for record in selected]
    if args.records_out:
        args.records_out.parent.mkdir(parents=True, exist_ok=True)
        args.records_out.write_text(json.dumps(mapped, indent=2, sort_keys=True) + "\n")
    result: dict[str, object] = {
        "source_records": len(records),
        "selected": len(mapped),
        "excluded_old_completed": excluded,
    }
    if args.staging_database:
        if args.wiki_root is None:
            parser.error("--wiki-root is required with --staging-database")
        result["staging"] = import_to_database(mapped, args.staging_database, args.wiki_root)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
