#!/usr/bin/env python3
"""Print deterministic, read-only checkbox observations and diagnostics as JSON."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from lifeos.wiki_checkbox_tasks import CheckboxTaskScanPolicy, scan_checkbox_tasks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki-root", default="/wiki", help="canonical wiki root to scan")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="DIRECTORY",
        help="additional root-relative directory name to exclude; may be repeated",
    )
    args = parser.parse_args()
    result = scan_checkbox_tasks(args.wiki_root, policy=CheckboxTaskScanPolicy(exclusions=tuple(args.exclude)))
    print(
        json.dumps(
            {
                "tasks": [asdict(task) for task in result.tasks],
                "diagnostics": [asdict(diagnostic) for diagnostic in result.diagnostics],
                "policy": {
                    "allowed_roots": list(result.effective_allowed_roots),
                    "exclusions": list(result.effective_exclusions),
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
