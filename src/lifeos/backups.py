"""Normal SQLite and wiki backup creation and verification primitives."""

from __future__ import annotations

import sqlite3
import tarfile
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
OPTIONAL_TABLES = {"metric_definitions", "metric_entries", "routine_skips", "goal_milestones", "task_dependencies"}


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


def backup_wiki(source: Path, destination: Path) -> Path:
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_dir() or source.is_symlink():
        raise ValueError("wiki source must be a non-symlink directory")
    if destination == source or source in destination.parents:
        raise ValueError("wiki backup destination must be outside the wiki root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w") as archive:
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"wiki source contains a symlink: {path}")
            if path.is_file():
                archive.add(path, arcname=path.relative_to(source).as_posix(), recursive=False)
    return destination
