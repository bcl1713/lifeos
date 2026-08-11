#!/usr/bin/env python3
"""Export the complete LifeOS SQLite database to portable JSON."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def export_database(database: Path, output: Path) -> dict[str, int]:
    engine = create_engine(f"sqlite:///{database}")
    inspector = inspect(engine)
    result: dict[str, list[dict]] = {}
    with engine.connect() as connection:
        for table in inspector.get_table_names():
            rows = connection.execute(text(f'SELECT * FROM "{table}"')).mappings().all()
            result[table] = [{key: _json_value(value) for key, value in row.items()} for row in rows]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"format": "lifeos-export-v1", "tables": result}, indent=2, sort_keys=True) + "\n")
    return {table: len(rows) for table, rows in result.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(export_database(args.database, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
