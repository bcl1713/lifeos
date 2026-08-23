#!/usr/bin/env python3
"""Verify that a LifeOS SQLite backup is readable and structurally complete."""

from __future__ import annotations

import argparse
from pathlib import Path

from lifeos.backups import verify_backup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    counts = verify_backup(args.database)
    print(f"verified={args.database} tasks={counts['tasks']} audit_records={counts['audit_records']}")


if __name__ == "__main__":
    main()
