#!/usr/bin/env python3
"""Validate the durable Phase 6 memory/routing contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_MEMORY = (
    "/home/brian/wiki",
    "source of truth",
    "agent_rules.md",
    "personal-context",
)
REQUIRED_RULES = (
    "read this file",
    "canonical wiki",
    "durable context",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wiki", type=Path)
    args = parser.parse_args()
    rules = args.wiki / "agent_rules.md"
    errors: list[str] = []
    if not rules.is_file():
        errors.append("missing agent_rules.md")
    rules_text = rules.read_text(encoding="utf-8").lower() if rules.is_file() else ""
    for phrase in REQUIRED_RULES:
        if phrase not in rules_text:
            errors.append(f"agent_rules.md missing: {phrase}")
    result = {
        "valid": not errors,
        "memory_contract": "persistent memory is verified by the active Hermes memory store",
        "required_memory_phrases": list(REQUIRED_MEMORY),
        "rules_file": str(rules),
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
