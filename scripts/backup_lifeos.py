#!/usr/bin/env python3
"""Create a consistent SQLite backup while the application is live."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from lifeos.backups import backup_database


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
