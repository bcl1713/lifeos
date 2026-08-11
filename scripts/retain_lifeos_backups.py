#!/usr/bin/env python3
"""Apply the LifeOS 30-daily/12-monthly backup retention policy."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def backup_stamp(path: Path) -> datetime:
    try:
        stamp = path.stem.removeprefix("lifeos-").removesuffix(".db")
        return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def retention_plan(directory: Path, daily: int = 30, monthly: int = 12) -> tuple[list[Path], list[Path]]:
    files = sorted(directory.glob("lifeos-*.db"), key=backup_stamp, reverse=True)
    latest_by_day: dict[str, Path] = {}
    latest_by_month: dict[str, Path] = {}
    for path in files:
        stamp = backup_stamp(path)
        latest_by_day.setdefault(stamp.date().isoformat(), path)
        latest_by_month.setdefault(stamp.strftime("%Y-%m"), path)
    keep = set(list(latest_by_day.values())[:daily]) | set(list(latest_by_month.values())[:monthly])
    return sorted(keep), sorted(set(files) - keep)


def apply_retention(directory: Path, daily: int = 30, monthly: int = 12, apply: bool = False) -> dict[str, object]:
    keep, remove = retention_plan(directory, daily, monthly)
    if apply:
        for path in remove:
            path.unlink()
    return {"kept": [str(path) for path in keep], "removed": [str(path) for path in remove], "applied": apply}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--daily", type=int, default=30)
    parser.add_argument("--monthly", type=int, default=12)
    parser.add_argument("--apply", action="store_true", help="delete files outside the retention set")
    args = parser.parse_args()
    print(json.dumps(apply_retention(args.directory, args.daily, args.monthly, args.apply), indent=2))


if __name__ == "__main__":
    main()
