"""Executable contract for the future read-only wiki checkbox scanner.

This test intentionally validates specification fixtures only. Scanner behavior is
implemented in issue #58; that implementation must consume this contract rather
than change canonical Markdown to suit a parser.
"""

from __future__ import annotations

import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "wiki_checkbox_tasks"
MANIFEST_PATH = FIXTURE_ROOT / "expected.json"
SPEC_PATH = REPOSITORY_ROOT / "docs" / "wiki-checkbox-task-grammar.md"


def _line(path: Path, number: int) -> str:
    return path.read_text(encoding="utf-8").splitlines()[number - 1]


def test_fixture_manifest_locs_are_exact_and_deterministically_sorted() -> None:
    """Keep future scanner assertions tied to real canonical Markdown fixtures."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    task_locations = [(item["source_path"], item["line"]) for item in manifest["tasks"]]
    diagnostic_locations = [
        (item["source_path"], item["line"], item["code"]) for item in manifest["diagnostics"]
    ]
    assert task_locations == sorted(task_locations)
    assert diagnostic_locations == sorted(diagnostic_locations)

    for task in manifest["tasks"]:
        assert _line(FIXTURE_ROOT / task["source_path"], task["line"]) == task["source_line"]
    for diagnostic in manifest["diagnostics"]:
        assert _line(FIXTURE_ROOT / diagnostic["source_path"], diagnostic["line"]) == diagnostic["source_line"]
    for excluded_path in manifest["excluded_paths"]:
        assert "- [ ]" in (FIXTURE_ROOT / excluded_path).read_text(encoding="utf-8")


def test_specification_covers_each_fixture_contract_and_safety_boundary() -> None:
    """Pin the #57 grammar, identity, safety, and purity decisions for #58."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    specification = SPEC_PATH.read_text(encoding="utf-8")

    required_phrases = (
        "- [ ]",
        "- [x]",
        "01-Projects",
        "02-Areas",
        "dailies",
        "03-Research",
        "04-Archives",
        "templates",
        "path, then line",
        "checkbox occurrence",
        "linked task record",
        "content fingerprint",
        "status is metadata-only",
        "no filesystem source writes",
        "no DB dependency",
        "no task/projection mutation",
        "root containment",
        "MALFORMED_CHECKBOX",
        "UNSAFE_TASK_LINK",
        "MISSING_TASK_RECORD",
        "UNTYPED_TASK_RECORD",
        "WRONG_TASK_RECORD_TYPE",
        "DUPLICATE_LINKED_TASK_RECORD",
        "CHECKBOX_STATUS_DISAGREEMENT",
        "source_path",
        "line",
        "column",
        "source_excerpt",
        "legacy typed task records",
        "daily capture",
        "moves and renames",
    )
    for phrase in required_phrases:
        assert phrase in specification

    assert {item["code"] for item in manifest["diagnostics"]} == {
        "MALFORMED_CHECKBOX",
        "UNSAFE_TASK_LINK",
        "MISSING_TASK_RECORD",
        "UNTYPED_TASK_RECORD",
        "WRONG_TASK_RECORD_TYPE",
        "DUPLICATE_LINKED_TASK_RECORD",
        "CHECKBOX_STATUS_DISAGREEMENT",
    }
    disagreement = next(item for item in manifest["diagnostics"] if item["code"] == "CHECKBOX_STATUS_DISAGREEMENT")
    assert disagreement == {
        "code": "CHECKBOX_STATUS_DISAGREEMENT",
        "severity": "warning",
        "message": "Checkbox is open but linked task record status is completed; checkbox state remains authoritative.",
        "source_path": "01-Projects/Alpha/index.md",
        "line": 10,
        "source_line": "- [ ] [Completed record](lifeos/tasks/completed-record.md)",
        "link_destination": "lifeos/tasks/completed-record.md",
        "linked_record_path": "01-Projects/Alpha/lifeos/tasks/completed-record.md",
    }
    assert any(item["linked_task_id"] is None for item in manifest["tasks"])
    assert any(item["checked"] for item in manifest["tasks"])
    assert any(not item["checked"] for item in manifest["tasks"])
