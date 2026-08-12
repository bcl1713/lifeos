#!/usr/bin/env python3
"""Validate the Phase 9 task-authority cutover contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

FORBIDDEN = ("tasks create", "tasks update", "tasks complete", "tasks delete")
REQUIRED_RULES = (
    "read-only",
    "lifeos",
    "source to be imported",
    "no duplicate",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wiki", type=Path)
    parser.add_argument("cron", type=Path)
    args = parser.parse_args()
    errors: list[str] = []
    project = args.wiki / "01-Projects/LifeOS/index.md"
    rules = args.wiki / "agent_rules.md"
    text = project.read_text(encoding="utf-8").lower() if project.is_file() else ""
    rules_text = rules.read_text(encoding="utf-8").lower() if rules.is_file() else ""
    cron_text = ""
    jobs = args.cron / "jobs.json"
    if jobs.is_file():
        cron_text = jobs.read_text(encoding="utf-8").lower()
    else:
        errors.append("missing cron jobs.json")
    if "phase nine" not in text:
        errors.append("canonical project note missing Phase 9")
    for phrase in REQUIRED_RULES:
        if phrase not in text and phrase not in rules_text:
            errors.append(f"cutover contract missing: {phrase}")
    for phrase in FORBIDDEN:
        if phrase in cron_text:
            errors.append(f"scheduled workflow contains forbidden Google Tasks writer: {phrase}")
    result = {
        "valid": not errors,
        "project_note": str(project),
        "cron_jobs": str(jobs),
        "forbidden_writers_checked": list(FORBIDDEN),
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
