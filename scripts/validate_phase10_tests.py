#!/usr/bin/env python3
"""Validate the Phase 10 LifeOS test and artifact contract."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REQUIRED_TEST_FILES = {
    "tests/test_persistence.py": ("initialize_database", "session.commit", "stored"),
    "tests/test_auth.py": ("login", "logout", "agent"),
    "tests/test_tasks.py": ("dependency", "audit", "complete"),
    "tests/test_routine_generation.py": ("skip", "cadence", "frequency"),
    "tests/test_context_api.py": ("goal", "project", "milestone"),
    "tests/test_metric_api.py": ("metric", "assert"),
    "tests/test_source_api.py": ("source", "assert"),
    "tests/test_google_tasks_migration.py": ("migrat", "assert"),
    "tests/test_backup.py": ("backup", "restore", "assert"),
    "tests/test_web_ui.py": ("login", "read-only", "mutation"),
    "tests/test_export_retention.py": ("export", "retention"),
    "tests/test_health.py": ("health",),
}
REQUIRED_ARTIFACTS = (
    "scripts/backup_lifeos.py",
    "scripts/restore_lifeos.py",
    "scripts/export_lifeos.py",
    "scripts/validate_wiki_provenance.py",
    "scripts/validate_phase9_cutover.py",
    "Dockerfile",
    "migrations",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    args = parser.parse_args()
    errors: list[str] = []
    coverage: dict[str, bool] = {}
    for relative, phrases in REQUIRED_TEST_FILES.items():
        path = args.repository / relative
        text = path.read_text(encoding="utf-8").lower() if path.is_file() else ""
        ok = path.is_file() and all(phrase in text for phrase in phrases)
        coverage[relative] = ok
        if not ok:
            errors.append(f"missing or insufficient focused coverage: {relative}")
    for relative in REQUIRED_ARTIFACTS:
        if not (args.repository / relative).exists():
            errors.append(f"missing validation artifact: {relative}")
    secrets = re.compile(r"(?:password|token|secret)\s*[:=]\s*[\"'][^\"']{12,}[\"']", re.I)
    for path in args.repository.rglob("*.py"):
        if ".venv" in path.parts or ".git" in path.parts or "tests" in path.parts:
            continue
        if secrets.search(path.read_text(encoding="utf-8", errors="ignore")):
            errors.append(f"possible hard-coded secret: {path.relative_to(args.repository)}")
    result = {
        "valid": not errors,
        "focused_test_files": len(REQUIRED_TEST_FILES),
        "covered_test_files": sum(coverage.values()),
        "required_artifacts": len(REQUIRED_ARTIFACTS),
        "coverage": coverage,
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
