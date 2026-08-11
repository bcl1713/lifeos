#!/usr/bin/env python3
"""Validate the lightweight frontmatter/provenance contract for the wiki.

Legacy notes without frontmatter are reported but remain valid; new or edited
notes can opt into the schema without requiring a disruptive corpus rewrite.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REQUIRED_FIELDS = {"id", "record_status", "epistemic", "verification"}
PROVENANCE_FIELDS = REQUIRED_FIELDS - {"id"}
ID_PATTERN = re.compile(r"^id:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", re.MULTILINE)


def parse_frontmatter(path: Path) -> tuple[dict[str, str], str] | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError("unterminated frontmatter")
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip("\"'")
    return fields, text[end + 4 :]


def validate_wiki(root: Path) -> dict[str, object]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    ids: dict[str, str] = {}
    notes = 0
    frontmatter_notes = 0
    for path in sorted(root.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        notes += 1
        try:
            parsed = parse_frontmatter(path)
        except ValueError as exc:
            errors.append({"path": str(path.relative_to(root)), "error": str(exc)})
            continue
        if parsed is None:
            warnings.append({"path": str(path.relative_to(root)), "warning": "legacy note has no frontmatter"})
            continue
        fields, _body = parsed
        if not (path.relative_to(root).parts[0] == "templates"):
            present_provenance = PROVENANCE_FIELDS & fields.keys()
            if present_provenance and present_provenance != PROVENANCE_FIELDS:
                missing = sorted(PROVENANCE_FIELDS - fields.keys())
                errors.append(
                    {
                        "path": str(path.relative_to(root)),
                        "error": f"partial provenance frontmatter: {', '.join(missing)}",
                    }
                )
            elif not present_provenance:
                warnings.append(
                    {
                        "path": str(path.relative_to(root)),
                        "warning": "legacy frontmatter has no provenance fields",
                    }
                )
        frontmatter_notes += 1
        identifier = fields.get("id", "")
        if identifier:
            relative = str(path.relative_to(root))
            if identifier in ids:
                warnings.append(
                    {
                        "path": relative,
                        "warning": f"duplicate legacy id {identifier!r}; first seen at {ids[identifier]}",
                    }
                )
            else:
                ids[identifier] = relative
    return {
        "root": str(root),
        "notes": notes,
        "frontmatter_notes": frontmatter_notes,
        "legacy_notes": len(warnings),
        "unique_ids": len(ids),
        "errors": errors,
        "warnings": warnings,
        "valid": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    result = validate_wiki(args.root.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
