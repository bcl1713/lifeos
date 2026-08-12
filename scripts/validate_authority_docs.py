#!/usr/bin/env python3
"""Validate that operator documentation describes one canonical wiki authority."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DOCUMENTS = ("README.md", "docs/architecture.md", "docs/operations.md")
REQUIRED_CONTRACTS = {
    "canonical wiki authority": ("wiki", "canonical"),
    "rebuildable SQLite projection": ("sqlite", "rebuildable", "projection"),
    "source-first mutation": ("source-first",),
    "conflict detection": ("expected_hash", "409"),
    "reconciliation": ("reconciliation",),
}
REQUIRED_DOMAIN_TYPES = ("task", "project", "area", "goal", "routine")
FORBIDDEN_CLAIMS = (
    "sqlite-backed crud",
    "sqlite is the system of record",
    "active task state is authoritative in lifeos",
    "lifeos owns durable tasks",
    "lifeos is the active task authority",
)


def validate_authority_docs(repository: Path) -> dict[str, object]:
    errors: list[str] = []
    contents: dict[str, str] = {}
    for relative in DOCUMENTS:
        path = repository / relative
        if not path.is_file():
            errors.append(f"missing authority document: {relative}")
            continue
        contents[relative] = path.read_text(encoding="utf-8").lower()

    combined = "\n".join(contents.values())
    for claim in FORBIDDEN_CLAIMS:
        if claim in combined:
            errors.append(f"forbidden authority claim: {claim}")
    for label, terms in REQUIRED_CONTRACTS.items():
        if not all(term in combined for term in terms):
            errors.append(f"missing {label} contract: {', '.join(terms)}")
    for record_type in REQUIRED_DOMAIN_TYPES:
        if record_type not in combined:
            errors.append(f"missing canonical domain type: {record_type}")

    return {
        "valid": not errors,
        "checked_documents": len(contents),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    args = parser.parse_args()
    result = validate_authority_docs(args.repository)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
