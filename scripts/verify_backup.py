#!/usr/bin/env python3
"""Verify that a LifeOS SQLite backup is readable and structurally complete."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

REQUIRED_TABLES = {
    "users",
    "sessions",
    "agent_credentials",
    "task_lists",
    "tasks",
    "goals",
    "projects",
    "routines",
    "audit_records",
}
OPTIONAL_TABLES = {"metric_definitions", "metric_entries"}


def verify_backup(database: Path) -> dict[str, int]:
    if not database.exists():
        raise FileNotFoundError(database)
    with sqlite3.connect(database) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"integrity_check={integrity}")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = REQUIRED_TABLES - tables
        if missing:
            raise RuntimeError(f"missing_tables={','.join(sorted(missing))}")
        counts = {
            "tasks": connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
            "audit_records": connection.execute("SELECT COUNT(*) FROM audit_records").fetchone()[0],
        }
        for table in OPTIONAL_TABLES & tables:
            counts[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    counts = verify_backup(args.database)
    print(f"verified={args.database} tasks={counts['tasks']} audit_records={counts['audit_records']}")


if __name__ == "__main__":
    main()
