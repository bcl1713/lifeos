#!/usr/bin/env python3
"""Create a consistent SQLite backup while the application is live."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def backup_database(source: Path, destination: Path) -> Path:
    source = source.resolve()
    destination = destination.resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination == source:
        raise ValueError("backup destination must differ from source")
    with sqlite3.connect(source) as source_connection:
        source_connection.execute("PRAGMA wal_checkpoint(FULL)")
        with sqlite3.connect(destination) as destination_connection:
            source_connection.backup(destination_connection)
            destination_connection.execute("PRAGMA integrity_check")
            destination_connection.commit()
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("/data/lifeos.db"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or Path("/backups") / f"lifeos-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.db"
    result = backup_database(args.database, output)
    print(f"backup={result} bytes={result.stat().st_size}")


if __name__ == "__main__":
    main()
