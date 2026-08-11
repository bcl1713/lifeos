#!/usr/bin/env python3
"""Restore a verified LifeOS SQLite backup into a new database."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def restore_database(backup: Path, destination: Path, *, overwrite: bool = False) -> Path:
    backup = backup.resolve()
    destination = destination.resolve()
    if not backup.exists():
        raise FileNotFoundError(backup)
    if backup == destination:
        raise ValueError("restore destination must differ from backup")
    if destination.exists() and not overwrite:
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    with sqlite3.connect(backup) as source, sqlite3.connect(destination) as target:
        source.backup(target)
        integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"restored integrity_check={integrity}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    result = restore_database(args.backup, args.destination, overwrite=args.overwrite)
    print(f"restored={result} bytes={result.stat().st_size}")


if __name__ == "__main__":
    main()
