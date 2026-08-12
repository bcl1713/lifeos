#!/usr/bin/env python3
"""Validate that the LifeOS project deliverables agree with live intent evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_FILES = (
    "README.md",
    "LICENSE",
    "Dockerfile",
    ".env.example",
    "compose.dev.yaml",
    "docs/architecture.md",
    "docs/operations.md",
    "scripts/backup_lifeos.py",
    "scripts/restore_lifeos.py",
    "scripts/export_lifeos.py",
    "scripts/validate_phase10_tests.py",
)
REQUIRED_DOC_PHRASES = (
    "v0.3.8",
    "Git-backed",
    "lifeos.hblucas.org",
    "30 daily / 12 monthly",
    "read-only historical",
    "pre-recreation backup",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    args = parser.parse_args()
    errors: list[str] = []
    for relative in REQUIRED_FILES:
        if not (args.repository / relative).exists():
            errors.append(f"missing promised deliverable: {relative}")
    operations = (
        (args.repository / "docs/operations.md").read_text(encoding="utf-8").lower()
        if (args.repository / "docs/operations.md").is_file()
        else ""
    )
    for phrase in REQUIRED_DOC_PHRASES:
        if phrase.lower() not in operations:
            errors.append(f"operations documentation missing current contract: {phrase}")
    readme = (
        (args.repository / "README.md").read_text(encoding="utf-8") if (args.repository / "README.md").is_file() else ""
    )
    if "Secrets never belong" not in readme and "Secrets" not in readme:
        errors.append("README missing secret-boundary statement")
    result = {
        "valid": not errors,
        "required_deliverables": len(REQUIRED_FILES),
        "checked_documentation_phrases": len(REQUIRED_DOC_PHRASES),
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
