import json
import subprocess
import sys
from pathlib import Path

from lifeos.daily_capture_scan import scan_daily_captures
from lifeos.wiki_store import WikiRepository


def test_scan_emits_a_project_proposal_for_an_explicit_valid_capture(tmp_path: Path) -> None:
    repository = WikiRepository(tmp_path / "wiki")
    project = repository.write("project", "Kitchen", {"id": "prj-kitchen", "status": "active"})
    daily = repository.root / "Daily" / "2026-08-23.md"
    daily.parent.mkdir(parents=True)
    daily.write_text(
        "- [ ] [lifeos-capture id=dcap-20260823-001 target=project:prj-kitchen "
        "due=2026-08-30 priority=2] Book contractor\n",
        encoding="utf-8",
    )

    report = scan_daily_captures(repository, daily_root="Daily", start="2026-08-23", end="2026-08-23")

    assert report == {
        "proposals": [
            {
                "capture_id": "dcap-20260823-001",
                "source_path": "Daily/2026-08-23.md",
                "source_line": 1,
                "source_hash": "c637d6a9a7e5e0fda022f0d5b6e03c5d63bf0dcaa73123e292c1958824e67976",
                "title": "Book contractor",
                "target": {"type": "project", "id": project.record_id, "path": project.path},
                "due": "2026-08-30",
                "priority": 2,
            }
        ],
        "exceptions": [],
    }


def _daily(repository: WikiRepository, text: str, name: str = "2026-08-23.md") -> Path:
    path = repository.root / "Daily" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_scan_reports_malformed_and_ambiguous_targets_without_proposals(tmp_path: Path) -> None:
    repository = WikiRepository(tmp_path / "wiki")
    _daily(
        repository,
        "\n".join(
            [
                "- [ ] ordinary checkbox is ignored",
                "- [ ] [lifeos-capture id=dcap-001] Missing target",
                "- [ ] [lifeos-capture id=dcap-002 target=project] Ambiguous target",
            ]
        )
        + "\n",
    )

    report = scan_daily_captures(repository, daily_root="Daily", start="2026-08-23", end="2026-08-23")

    assert report["proposals"] == []
    assert [(item["capture_id"], item["code"]) for item in report["exceptions"]] == [
        (None, "malformed_capture"),
        ("dcap-002", "invalid_target"),
    ]


def test_scan_reports_duplicate_ids_and_stale_targets(tmp_path: Path) -> None:
    repository = WikiRepository(tmp_path / "wiki")
    repository.write("project", "Archived", {"id": "prj-archived", "status": "archived"})
    _daily(
        repository,
        "\n".join(
            [
                "- [ ] [lifeos-capture id=dcap-003 target=inbox] First duplicate",
                "- [ ] [lifeos-capture id=dcap-003 target=inbox] Second duplicate",
                "- [ ] [lifeos-capture id=dcap-004 target=project:prj-archived] Do not route",
            ]
        )
        + "\n",
    )

    report = scan_daily_captures(repository, daily_root="Daily", start="2026-08-23", end="2026-08-23")

    assert report["proposals"] == []
    assert [(item["capture_id"], item["code"]) for item in report["exceptions"]] == [
        ("dcap-003", "duplicate_capture_id"),
        ("dcap-003", "duplicate_capture_id"),
        ("dcap-004", "stale_target"),
    ]


def test_scan_is_idempotent_and_reports_promoted_or_changed_sources(tmp_path: Path) -> None:
    repository = WikiRepository(tmp_path / "wiki")
    daily = _daily(repository, "- [ ] [lifeos-capture id=dcap-005 target=inbox] Capture receipt\n")

    first = scan_daily_captures(repository, daily_root="Daily", start="2026-08-23", end="2026-08-23")
    second = scan_daily_captures(repository, daily_root="Daily", start="2026-08-23", end="2026-08-23")
    assert first == second
    proposal = first["proposals"][0]
    repository.write(
        "task",
        "Capture receipt",
        {
            "id": "tsk-capture-receipt",
            "status": "open",
            "task_list": "Inbox",
            "owner_type": "inbox",
            "daily_capture_id": proposal["capture_id"],
            "daily_capture_source_hash": proposal["source_hash"],
        },
        path="00-Inbox/tasks/capture-receipt-tsk-capture-receipt.md",
    )

    promoted = scan_daily_captures(repository, daily_root="Daily", start="2026-08-23", end="2026-08-23")
    assert promoted["proposals"] == []
    assert promoted["exceptions"][0]["code"] == "already_promoted"

    daily.write_text(
        "- [ ] [lifeos-capture id=dcap-005 target=inbox] Capture receipt with warranty\n", encoding="utf-8"
    )
    changed = scan_daily_captures(repository, daily_root="Daily", start="2026-08-23", end="2026-08-23")
    assert changed["proposals"] == []
    assert changed["exceptions"][0]["code"] == "source_changed"


def test_scan_does_not_mutate_daily_notes_or_canonical_wiki(tmp_path: Path) -> None:
    repository = WikiRepository(tmp_path / "wiki")
    project = repository.write("project", "Kitchen", {"id": "prj-kitchen", "status": "active"})
    _daily(repository, "- [ ] [lifeos-capture id=dcap-006 target=project:prj-kitchen] Book contractor\n")
    before = {
        path.relative_to(repository.root).as_posix(): path.read_bytes()
        for path in repository.root.rglob("*")
        if path.is_file()
    }

    report = scan_daily_captures(repository, daily_root="Daily", start="2026-08-23", end="2026-08-23")

    after = {
        path.relative_to(repository.root).as_posix(): path.read_bytes()
        for path in repository.root.rglob("*")
        if path.is_file()
    }
    assert report["proposals"][0]["target"]["id"] == project.record_id
    assert before == after


def test_scan_cli_prints_deterministic_json_without_creating_state(tmp_path: Path) -> None:
    repository = WikiRepository(tmp_path / "wiki")
    _daily(repository, "- [ ] [lifeos-capture id=dcap-007 target=inbox] Review receipt\n")
    before = {
        path.relative_to(repository.root).as_posix(): path.read_bytes()
        for path in repository.root.rglob("*")
        if path.is_file()
    }

    result = subprocess.run(
        [
            sys.executable,
            "scripts/scan_daily_captures.py",
            "--wiki-root",
            str(repository.root),
            "--daily-root",
            "Daily",
            "--from",
            "2026-08-23",
            "--to",
            "2026-08-23",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout)["proposals"][0]["capture_id"] == "dcap-007"
    after = {
        path.relative_to(repository.root).as_posix(): path.read_bytes()
        for path in repository.root.rglob("*")
        if path.is_file()
    }
    assert before == after


def test_scan_rejects_noncanonical_optional_values_and_daily_root_symlinks(tmp_path: Path) -> None:
    repository = WikiRepository(tmp_path / "wiki")
    _daily(
        repository,
        "\n".join(
            [
                "- [ ] [lifeos-capture id=dcap-008 target=inbox due=20260830] Noncanonical due",
                "- [ ] [lifeos-capture id=dcap-009 target=inbox priority=+1] Noncanonical priority",
            ]
        )
        + "\n",
    )
    linked_daily = repository.root / "LinkedDaily"
    linked_daily.symlink_to(repository.root / "Daily", target_is_directory=True)

    report = scan_daily_captures(repository, daily_root="Daily", start="2026-08-23", end="2026-08-23")

    assert report["proposals"] == []
    assert [(item["capture_id"], item["code"]) for item in report["exceptions"]] == [
        ("dcap-008", "malformed_capture"),
        ("dcap-009", "malformed_capture"),
    ]
    try:
        scan_daily_captures(repository, daily_root="LinkedDaily", start="2026-08-23", end="2026-08-23")
    except ValueError as exc:
        assert "non-symlink" in str(exc)
    else:
        raise AssertionError("scan accepted a symlinked daily root")


def test_scan_reports_canonical_authority_conflict(tmp_path: Path) -> None:
    repository = WikiRepository(tmp_path / "wiki")
    _daily(
        repository,
        "\n".join(
            [
                "- [ ] [lifeos-capture id=dcap-010 target=inbox] Valid duplicate",
                "- [ ] [lifeos-capture id=dcap-010 target=project] Invalid duplicate",
            ]
        )
        + "\n",
    )
    duplicate = repository.root / "00-Inbox" / "tasks" / "duplicate.md"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text(
        "---\n"
        "id: tsk-duplicate\n"
        "type: task\n"
        "title: Duplicate\n"
        "status: open\n"
        "task_list: Inbox\n"
        "owner_type: inbox\n"
        "---\n",
        encoding="utf-8",
    )
    duplicate_other = repository.root / "00-Inbox" / "tasks" / "duplicate-other.md"
    duplicate_other.write_text(duplicate.read_text(encoding="utf-8"), encoding="utf-8")

    report = scan_daily_captures(repository, daily_root="Daily", start="2026-08-23", end="2026-08-23")

    assert report == {
        "proposals": [],
        "exceptions": [
            {
                "capture_id": None,
                "source_path": "__canonical__",
                "source_line": 0,
                "code": "canonical_authority_conflict",
                "detail": (
                    "ambiguous canonical wiki IDs: tsk-duplicate: "
                    "00-Inbox/tasks/duplicate-other.md, 00-Inbox/tasks/duplicate.md"
                ),
            }
        ],
    }


def test_scan_reports_mixed_validity_duplicate_capture_ids(tmp_path: Path) -> None:
    repository = WikiRepository(tmp_path / "wiki")
    _daily(
        repository,
        "\n".join(
            [
                "- [ ] [lifeos-capture id=dcap-010 target=inbox] Valid duplicate",
                "- [ ] [lifeos-capture id=dcap-010 target=project] Invalid duplicate",
            ]
        )
        + "\n",
    )

    report = scan_daily_captures(repository, daily_root="Daily", start="2026-08-23", end="2026-08-23")

    assert report["proposals"] == []
    assert [(item["source_line"], item["code"]) for item in report["exceptions"]] == [
        (1, "duplicate_capture_id"),
        (2, "duplicate_capture_id"),
        (2, "invalid_target"),
    ]
