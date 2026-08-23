#!/usr/bin/env python3
"""Apply one approved capture proposal against an explicitly named test fixture root."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lifeos.capture_promotion import apply_reviewed_capture
from lifeos.db import create_engine, create_session_factory
from lifeos.wiki_store import WikiRepository

_PROTECTED_ROOTS = {Path("/wiki"), Path("/home/brian/wiki")}
_FIXTURE_MARKER = ".lifeos-fixture"
_FIXTURE_MARKER_CONTENT = "lifeos-test-fixture-v1\n"


def _json_file(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument(
        "--fixture-root", required=True, help="Explicit fixture wiki root; production roots are refused"
    )
    parser.add_argument("--proposal-file", required=True)
    parser.add_argument("--approval-file", required=True, help="Durable reviewed approval JSON")
    parser.add_argument("--apply", action="store_true", help="Perform the fixture-only canonical source writes")
    args = parser.parse_args()
    fixture_root = Path(args.fixture_root).resolve()
    if fixture_root in _PROTECTED_ROOTS:
        parser.error("fixture root must not be a protected production wiki root")
    marker = fixture_root / _FIXTURE_MARKER
    if marker.is_symlink() or not marker.is_file() or marker.read_text(encoding="utf-8") != _FIXTURE_MARKER_CONTENT:
        parser.error("fixture root must contain the expected fixture marker")
    proposal = _json_file(args.proposal_file)
    approval = _json_file(args.approval_file)
    if not args.apply:
        print(json.dumps({"status": "dry_run", "capture_id": proposal.get("capture_id")}, sort_keys=True))
        return 0
    engine = create_engine(args.database)
    factory = create_session_factory(engine)
    with factory() as session:
        result = apply_reviewed_capture(session, WikiRepository(fixture_root), proposal, approval, apply=True)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
