"""Regression coverage for deterministic read-only checkbox discovery."""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

import pytest

from lifeos.wiki_checkbox_tasks import CheckboxTaskScanPolicy, scan_checkbox_tasks

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "wiki_checkbox_tasks"
MANIFEST_PATH = FIXTURE_ROOT / "expected.json"


def _fixture_bytes() -> dict[str, bytes]:
    return {
        path.relative_to(FIXTURE_ROOT).as_posix(): path.read_bytes()
        for path in sorted(FIXTURE_ROOT.rglob("*"))
        if path.is_file()
    }


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_scans_fixture_contract_without_source_writes_or_mutable_results() -> None:
    before = _fixture_bytes()

    result = scan_checkbox_tasks(FIXTURE_ROOT)

    assert _fixture_bytes() == before
    manifest = _manifest()
    assert [(task.source_path, task.line, task.source_excerpt, task.checked, task.label) for task in result.tasks] == [
        (item["source_path"], item["line"], item["source_line"], item["checked"], item["label"])
        for item in manifest["tasks"]
    ]
    diagnostics = [
        (diagnostic.code, diagnostic.source_path, diagnostic.line, diagnostic.source_excerpt)
        for diagnostic in result.diagnostics
    ]
    assert diagnostics == [
        (item["code"], item["source_path"], item["line"], item["source_line"])
        for item in manifest["diagnostics"]
    ]
    assert result.effective_allowed_roots == ("01-Projects", "02-Areas", "dailies")
    assert result.effective_exclusions == ("03-Research", "04-Archives", "assets", "templates")
    assert all(task.column == task.source_excerpt.index("-") + 1 for task in result.tasks)
    assert all(diagnostic.severity == "warning" for diagnostic in result.diagnostics)
    assert all(not Path(task.source_path).is_absolute() for task in result.tasks)
    assert all(not Path(diagnostic.source_path).is_absolute() for diagnostic in result.diagnostics)
    with pytest.raises(FrozenInstanceError):
        result.tasks[0].label = "mutated"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.diagnostics[0].message = "mutated"  # type: ignore[misc]


def test_link_metadata_identity_status_and_duplicate_diagnostics_follow_contract() -> None:
    result = scan_checkbox_tasks(FIXTURE_ROOT)
    by_line = {task.line: task for task in result.tasks if task.source_path == "01-Projects/Alpha/index.md"}

    assert by_line[3].linked_task_id is None
    assert by_line[3].content_fingerprint == hashlib.sha256(
        b"01-Projects/Alpha/index.md\x00- [ ] Plan release"
    ).hexdigest()
    assert by_line[3].identity == "plain source-path plus content-fingerprint; read-only"
    assert by_line[4].linked_task_path == "01-Projects/Alpha/lifeos/tasks/change-brakes.md"
    assert by_line[4].linked_task_id == "tsk-change-brakes"
    assert by_line[4].identity == "tsk-change-brakes plus checkbox occurrence locator"
    assert by_line[10].linked_task_id == "tsk-completed-record"

    duplicate_lines = [
        diagnostic.line for diagnostic in result.diagnostics if diagnostic.code == "DUPLICATE_LINKED_TASK_RECORD"
    ]
    assert duplicate_lines == [4, 5]
    disagreement = next(
        diagnostic for diagnostic in result.diagnostics if diagnostic.code == "CHECKBOX_STATUS_DISAGREEMENT"
    )
    assert asdict(disagreement) == {
        "code": "CHECKBOX_STATUS_DISAGREEMENT",
        "severity": "warning",
        "message": "Checkbox is open but linked task record status is completed; checkbox state remains authoritative.",
        "source_path": "01-Projects/Alpha/index.md",
        "line": 10,
        "column": 1,
        "source_excerpt": "- [ ] [Completed record](lifeos/tasks/completed-record.md)",
        "link_destination": "lifeos/tasks/completed-record.md",
        "linked_record_path": "01-Projects/Alpha/lifeos/tasks/completed-record.md",
    }


def test_unsafe_missing_and_untyped_links_retain_plain_checkbox_observations(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source = wiki / "01-Projects" / "Alpha" / "index.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            (
                "- [ ] [Escape](../../../../outside.md)",
                "- [ ] [Absolute](/outside.md)",
                "- [ ] [URI](https://example.test/task.md)",
                "- [ ] [Fragment](lifeos/tasks/task.md#part)",
                "- [ ] [Query](lifeos/tasks/task.md?view=full)",
                "- [ ] [Missing](lifeos/tasks/missing.md)",
                "- [ ] [Untyped](lifeos/tasks/untyped.md)",
                "- [ ] [Wrong](lifeos/tasks/wrong.md)",
            )
        ),
        encoding="utf-8",
    )
    task_dir = source.parent / "lifeos" / "tasks"
    task_dir.mkdir(parents=True)
    (task_dir / "untyped.md").write_text("# Untyped\n", encoding="utf-8")
    (task_dir / "wrong.md").write_text("---\nid: prj-1\ntype: project\n---\n", encoding="utf-8")

    result = scan_checkbox_tasks(wiki)

    assert len(result.tasks) == 8
    assert all(task.linked_task_id is None for task in result.tasks)
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "UNSAFE_TASK_LINK",
        "UNSAFE_TASK_LINK",
        "UNSAFE_TASK_LINK",
        "UNSAFE_TASK_LINK",
        "UNSAFE_TASK_LINK",
        "MISSING_TASK_RECORD",
        "UNTYPED_TASK_RECORD",
        "WRONG_TASK_RECORD_TYPE",
    ]


def test_escaping_symlink_task_link_is_unsafe_without_reading_its_target(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source = wiki / "01-Projects" / "Alpha" / "index.md"
    source.parent.mkdir(parents=True)
    source.write_text("- [ ] [Outside](lifeos/tasks/outside.md)\n", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("---\nid: tsk-outside\ntype: task\n---\n", encoding="utf-8")
    task_dir = source.parent / "lifeos" / "tasks"
    task_dir.mkdir(parents=True)
    (task_dir / "outside.md").symlink_to(outside)

    result = scan_checkbox_tasks(wiki)

    assert result.tasks[0].linked_task_id is None
    assert [(diagnostic.code, diagnostic.linked_record_path) for diagnostic in result.diagnostics] == [
        ("UNSAFE_TASK_LINK", None)
    ]


def test_symlinked_task_link_inside_the_root_is_also_unsafe(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source = wiki / "01-Projects" / "Alpha" / "index.md"
    source.parent.mkdir(parents=True)
    source.write_text("- [ ] [Aliased](lifeos/tasks/alias.md)\n", encoding="utf-8")
    task_dir = source.parent / "lifeos" / "tasks"
    task_dir.mkdir(parents=True)
    target = task_dir / "target.md"
    target.write_text("---\nid: tsk-target\ntype: task\n---\n", encoding="utf-8")
    (task_dir / "alias.md").symlink_to(target)

    result = scan_checkbox_tasks(wiki)

    assert result.tasks[0].linked_task_id is None
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["UNSAFE_TASK_LINK"]


def test_ignores_excluded_hidden_and_non_markdown_paths_and_sorts_deterministically(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    for relative in (
        "02-Areas/B/index.md",
        "01-Projects/Z/index.md",
        "01-Projects/.hidden.md",
        "03-Research/ignored.md",
        "04-Archives/ignored.md",
        "templates/ignored.md",
        "assets/ignored.md",
    ):
        path = wiki / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("- [ ] keep out\n", encoding="utf-8")
    (wiki / "dailies").mkdir(parents=True)
    (wiki / "dailies" / "later.md").write_text("- [ ] second\n", encoding="utf-8")
    (wiki / "dailies" / "first.md").write_text("- [ ] first\n- [x] third\n", encoding="utf-8")
    (wiki / "dailies" / "not-markdown.txt").write_text("- [ ] ignored\n", encoding="utf-8")

    first = scan_checkbox_tasks(wiki)
    second = scan_checkbox_tasks(wiki)

    assert [(task.source_path, task.line) for task in first.tasks] == [
        ("01-Projects/Z/index.md", 1),
        ("02-Areas/B/index.md", 1),
        ("dailies/first.md", 1),
        ("dailies/first.md", 2),
        ("dailies/later.md", 1),
    ]
    assert first == second


def test_reports_deployment_added_exclusions_in_the_effective_policy(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    for relative in ("01-Projects/Alpha/index.md", "01-Projects/Alpha/generated/ignored.md"):
        path = wiki / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("- [ ] observation\n", encoding="utf-8")

    result = scan_checkbox_tasks(wiki, policy=CheckboxTaskScanPolicy(exclusions=("generated",)))

    assert [task.source_path for task in result.tasks] == ["01-Projects/Alpha/index.md"]
    assert result.effective_exclusions == ("03-Research", "04-Archives", "assets", "templates", "generated")


def test_reports_malformed_list_checkboxes_but_not_checkbox_like_prose(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source = wiki / "dailies" / "checklist.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            (
                "- [y] unsupported state",
                "- [ ]",
                "- [xx] extra state",
                "prose - [y] is not a list item",
                "1. [ ] ordered is unsupported prose",
                "* [ ] unsupported bullet",
                "- [ ] valid",
            )
        ),
        encoding="utf-8",
    )

    result = scan_checkbox_tasks(wiki)

    assert [(task.line, task.label) for task in result.tasks] == [(7, "valid")]
    assert [(diagnostic.code, diagnostic.line) for diagnostic in result.diagnostics] == [
        ("MALFORMED_CHECKBOX", 1),
        ("MALFORMED_CHECKBOX", 2),
        ("MALFORMED_CHECKBOX", 3),
    ]
