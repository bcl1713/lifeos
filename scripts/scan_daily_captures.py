#!/usr/bin/env python3
"""Print review-only daily-capture promotion proposals as deterministic JSON."""
from __future__ import annotations

import argparse
import json

from lifeos.daily_capture_scan import scan_daily_captures
from lifeos.wiki_store import WikiRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wiki-root", default="/wiki")
    parser.add_argument("--daily-root", required=True, help="relative daily-note directory inside --wiki-root")
    parser.add_argument("--from", dest="start", required=True, help="inclusive YYYY-MM-DD date")
    parser.add_argument("--to", dest="end", required=True, help="inclusive YYYY-MM-DD date")
    args = parser.parse_args()
    report = scan_daily_captures(
        WikiRepository(args.wiki_root), daily_root=args.daily_root, start=args.start, end=args.end
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
