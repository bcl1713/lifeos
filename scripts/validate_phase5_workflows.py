#!/usr/bin/env python3
"""Validate the durable Phase 5 capture/retrieval workflow contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_CAPTURE = {
    "authoritative existing note",
    "same-day event",
    "preserve the user",
    "smallest authoritative set",
    "superseded history",
    "representative search",
}
REQUIRED_RETRIEVAL = {
    "agent_rules.md",
    "original knowledge-base files",
    "canonical summary",
    "newer matching events",
    "source links",
    "current, historical, resolved, uncertain, and superseded",
    "cite note paths, source ids, and dates",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wiki", type=Path)
    args = parser.parse_args()
    project = args.wiki / "01-Projects/LifeOS/index.md"
    rules = args.wiki / "agent_rules.md"
    errors: list[str] = []
    warnings: list[str] = []
    if not project.is_file():
        errors.append(f"missing canonical project note: {project}")
        print(json.dumps({"valid": False, "errors": errors, "warnings": warnings}, indent=2))
        return 1
    text = project.read_text(encoding="utf-8").lower()
    if not rules.is_file():
        errors.append("missing agent_rules.md")
    for phrase in REQUIRED_CAPTURE:
        if phrase not in text:
            errors.append(f"capture workflow missing: {phrase}")
    for phrase in REQUIRED_RETRIEVAL:
        if phrase not in text:
            errors.append(f"retrieval workflow missing: {phrase}")
    if "completion criterion:" not in text:
        errors.append("retrieval workflow has no completion criterion")
    if "phase five" not in text:
        errors.append("canonical note has no Phase 5 heading")
    if "source-first" not in (rules.read_text(encoding="utf-8").lower() if rules.is_file() else ""):
        warnings.append("agent_rules.md does not repeat the source-first phrase; project workflow still enforces it")
    result = {
        "valid": not errors,
        "project_note": str(project),
        "rules_file": str(rules),
        "capture_requirements": len(REQUIRED_CAPTURE),
        "retrieval_requirements": len(REQUIRED_RETRIEVAL),
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
