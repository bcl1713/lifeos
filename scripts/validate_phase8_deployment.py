#!/usr/bin/env python3
"""Validate the durable Phase 8 LifeOS deployment contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_FILES = (
    "README.md",
    "Dockerfile",
    "docker-entrypoint.sh",
    "alembic.ini",
    "migrations",
    "src/lifeos",
    "tests",
    "scripts/backup_lifeos.py",
    "scripts/restore_lifeos.py",
    "scripts/export_lifeos.py",
)
REQUIRED_README = (
    "ghcr.io/bcl1713/lifeos",
    "healthz",
    "backup_lifeos.py",
    "/home/brian/wiki",
    "homelab-stacks",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    args = parser.parse_args()
    errors: list[str] = []
    for item in REQUIRED_FILES:
        if not (args.repository / item).exists():
            errors.append(f"missing repository artifact: {item}")
    readme = (
        (args.repository / "README.md").read_text(encoding="utf-8") if (args.repository / "README.md").is_file() else ""
    )
    for phrase in REQUIRED_README:
        if phrase not in readme:
            errors.append(f"README missing deployment contract: {phrase}")
    dockerfile = (
        (args.repository / "Dockerfile").read_text(encoding="utf-8")
        if (args.repository / "Dockerfile").is_file()
        else ""
    )
    entrypoint = (
        (args.repository / "docker-entrypoint.sh").read_text(encoding="utf-8")
        if (args.repository / "docker-entrypoint.sh").is_file()
        else ""
    )
    if "USER root" not in dockerfile or "runuser -u lifeos" not in entrypoint:
        errors.append("runtime identity contract must show root entrypoint plus unprivileged runuser")
    result = {
        "valid": not errors,
        "repository": str(args.repository),
        "required_artifacts": len(REQUIRED_FILES),
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
