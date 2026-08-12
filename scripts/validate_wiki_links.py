#!/usr/bin/env python3
"""Validate authoritative Project and Area index links without mutating the wiki."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")


def _resolve_candidates(root: Path, raw: str) -> tuple[str, list[str]]:
    candidate = (root / raw.strip()).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return "traversal", []
    options = [candidate]
    if candidate.suffix.casefold() != ".md":
        options.extend((candidate.with_suffix(".md"), candidate / "index.md", candidate / "Index.md"))
        parent = candidate.parent
        if parent.is_dir():
            expected_names = {f"{candidate.name}.md".casefold(), candidate.name.casefold()}
            options.extend(
                path for path in parent.iterdir() if path.is_file() and path.name.casefold() in expected_names
            )
    matches: list[Path] = []
    physical: set[tuple[int, int]] = set()
    for option in options:
        if not option.is_file():
            continue
        stat = option.stat()
        identity = (stat.st_dev, stat.st_ino)
        if identity in physical:
            continue
        physical.add(identity)
        matches.append(option)
    if not matches:
        return "missing", []
    if len(matches) > 1:
        return "ambiguous", [path.relative_to(root).as_posix() for path in matches]
    return "valid", [matches[0].relative_to(root).as_posix()]


def validate_wiki_links(wiki_root: str | Path) -> dict[str, Any]:
    root = Path(wiki_root).resolve()
    errors: list[dict[str, Any]] = []
    checked = 0
    valid = 0
    for category, index_path in (
        ("project", root / "01-Projects/index.md"),
        ("area", root / "02-Areas/index.md"),
    ):
        if not index_path.is_file():
            errors.append({"type": category, "index": index_path.relative_to(root).as_posix(), "target": None, "status": "missing_index", "matches": []})
            continue
        for target in _LINK.findall(index_path.read_text(encoding="utf-8")):
            checked += 1
            status, matches = _resolve_candidates(root, target)
            if status == "valid":
                valid += 1
            else:
                errors.append(
                    {
                        "type": category,
                        "index": index_path.relative_to(root).as_posix(),
                        "target": target.strip(),
                        "status": status,
                        "matches": matches,
                    }
                )
    return {"valid": not errors, "checked_links": checked, "valid_links": valid, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wiki_root", nargs="?", default="/wiki")
    args = parser.parse_args()
    report = validate_wiki_links(args.wiki_root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
