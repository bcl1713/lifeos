#!/usr/bin/env python3
"""Validate the Phase 7 LifeOS skill contract against Hermes' skill store."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REQUIRED = {
    "life-knowledge-base",
    "life-tracker",
    "goal-planning",
    "project-context",
    "life-review",
    "resource-library",
}
REQUIRED_SECTIONS = ("## Overview", "## Steps", "## Pitfalls", "## Verification Checklist")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("skills_root", type=Path)
    args = parser.parse_args()
    errors: list[str] = []
    found: set[str] = set()
    for name in sorted(REQUIRED):
        path = args.skills_root / "productivity" / name / "SKILL.md"
        if not path.is_file():
            errors.append(f"missing skill file: {name}")
            continue
        found.add(name)
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            errors.append(f"{name}: frontmatter does not start at byte 0")
        if not re.search(r"\n---\n", text):
            errors.append(f"{name}: frontmatter closing marker missing")
        if f"name: {name}" not in text:
            errors.append(f"{name}: name field missing or mismatched")
        description = re.search(r'^description:\s*["\']?(.+?)["\']?$', text, re.MULTILINE)
        if not description or not description.group(1).strip().endswith("."):
            errors.append(f"{name}: description is missing or not a sentence")
        for section in REQUIRED_SECTIONS:
            if section not in text:
                errors.append(f"{name}: missing {section}")
    result = {
        "valid": not errors and found == REQUIRED,
        "required": sorted(REQUIRED),
        "found": sorted(found),
        "skill_count": len(found),
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
