"""Fixture-only capture-promotion contracts.

The reviewed scanner envelope is the scanner's unmodified proposal
(``capture_id``, ``source_path``, ``source_line``, exact-line ``source_hash``,
``title``, ``target`` of ``{type, id, path}``, ``due``, and ``priority``) plus a
durable approval. Approval contains ``approval_id``, ``approved_proposal`` equal
to that full proposal, and the SHA-256 ``proposal_fingerprint`` of canonical JSON.
The bridge must derive task fields and owner-local placement from this envelope;
callers must not translate it into ``task`` or ``{owner_id, task_list}``.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

import lifeos.capture_promotion as capture_promotion
from lifeos.capture_promotion import (
    CapturePromotionError,
    CapturePromotionReconciliationRequired,
    apply_reviewed_capture,
    generate_review_record,
)
from lifeos.daily_capture_scan import scan_daily_captures
from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import Task, TaskList
from lifeos.scripts_bridge import reconcile_wiki_projection
from lifeos.wiki_store import WikiRepository


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _line_sha256(path: Path, line: int) -> str:
    return hashlib.sha256(path.read_text(encoding="utf-8").splitlines()[line - 1].encode("utf-8")).hexdigest()


def _proposal(capture: Path, *, target: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "capture_id": "cap-2026-08-23-follow-up",
        "source_path": "00-Daily/2026-08-23.md",
        "source_hash": _line_sha256(capture, 3),
        "source_line": 3,
        "title": "Follow up with supplier",
        "target": target or {"type": "inbox", "id": None, "path": "00-Inbox"},
        "due": None,
        "priority": 2,
    }


def _approval(proposal: dict[str, object]) -> dict[str, object]:
    return _scanner_approval(proposal)


def _scanner_approval(proposal: dict[str, object]) -> dict[str, object]:
    canonical = json.dumps(proposal, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "approval_id": "apr-2026-08-23-scanner-01",
        "approved_proposal": proposal,
        "proposal_fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _scan_fixture_proposal(repository: WikiRepository) -> tuple[Path, dict[str, object]]:
    capture = repository.root / "Daily/2026-08-23.md"
    capture.parent.mkdir(parents=True, exist_ok=True)
    capture.write_text(
        "# 2026-08-23\n\n"
        "- [ ] [lifeos-capture id=cap-2026-08-23-scanned target=inbox due=2026-08-30 priority=2] "
        "Follow up with supplier\n",
        encoding="utf-8",
    )
    report = scan_daily_captures(repository, daily_root="Daily", start="2026-08-23", end="2026-08-23")
    assert report["exceptions"] == []
    return capture, report["proposals"][0]


def _setup(tmp_path: Path):
    wiki = tmp_path / "fixture-wiki"
    wiki.mkdir()
    (wiki / ".lifeos-fixture").write_text("lifeos-test-fixture-v1\n", encoding="utf-8")
    capture = wiki / "00-Daily/2026-08-23.md"
    capture.parent.mkdir(parents=True)
    capture.write_text("# 2026-08-23\n\n- [ ] Follow up with supplier\n", encoding="utf-8")
    engine = create_engine(f"sqlite:///{tmp_path / 'lifeos.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(TaskList(name="Inbox"))
        session.commit()
    return wiki, capture, factory


def test_reviewed_capture_apply_writes_one_owner_local_task_and_idempotent_receipt(tmp_path: Path) -> None:
    wiki, capture, factory = _setup(tmp_path)
    repository = WikiRepository(wiki)
    proposal = _proposal(capture)

    with factory() as session:
        result = apply_reviewed_capture(session, repository, proposal, _approval(proposal), apply=True)
        rerun = apply_reviewed_capture(session, repository, proposal, _approval(proposal), apply=True)

        task = session.scalar(select(Task))
        assert result["status"] == "applied"
        assert rerun == {"status": "unchanged", "capture_id": "cap-2026-08-23-follow-up", "task_wiki_id": task.wiki_id}
        assert task.wiki_id == "tsk-capture-cap-2026-08-23-follow-up"
        assert task.task_list.name == "Inbox"
        assert task.source_ref == "capture:cap-2026-08-23-follow-up"
        task_record = repository.find_by_id(task.wiki_id)
        assert task_record is not None
        assert task_record.fields["capture_promotion"]["approval_id"] == "apr-2026-08-23-scanner-01"
        assert capture.read_text(encoding="utf-8").count("capture-receipt: cap-2026-08-23-follow-up") == 1
        assert reconcile_wiki_projection(session, repository)["aligned"] is True


def test_reviewed_scanner_proposal_applies_without_translation_and_is_idempotent(tmp_path: Path) -> None:
    wiki, _capture, factory = _setup(tmp_path)
    repository = WikiRepository(wiki)
    capture, proposal = _scan_fixture_proposal(repository)
    approval = _scanner_approval(proposal)

    with factory() as session:
        applied = apply_reviewed_capture(session, repository, proposal, approval, apply=True)
        rerun = apply_reviewed_capture(session, repository, proposal, approval, apply=True)

        task = session.scalar(select(Task).where(Task.wiki_id == applied["task_wiki_id"]))
        assert task is not None
        assert task.title == proposal["title"]
        assert task.priority == proposal["priority"]
        assert task.due_date == date.fromisoformat(str(proposal["due"]))
        assert task.owner_type == "inbox"
        assert rerun == {"status": "unchanged", "capture_id": proposal["capture_id"], "task_wiki_id": task.wiki_id}
    assert capture.read_text(encoding="utf-8").count("capture-receipt: cap-2026-08-23-scanned") == 1


def test_reviewed_scanner_proposal_without_due_or_priority_applies_without_translation(tmp_path: Path) -> None:
    wiki, _capture, factory = _setup(tmp_path)
    repository = WikiRepository(wiki)
    capture = repository.root / "Daily/2026-08-23.md"
    capture.parent.mkdir(parents=True, exist_ok=True)
    capture.write_text(
        "# 2026-08-23\n\n"
        "- [ ] [lifeos-capture id=cap-no-priority target=inbox] No priority supplied\n",
        encoding="utf-8",
    )
    scan = scan_daily_captures(repository, daily_root="Daily", start="2026-08-23", end="2026-08-23")
    assert scan["exceptions"] == []
    proposal = scan["proposals"][0]
    assert proposal["due"] is None
    assert proposal["priority"] is None
    approval = _scanner_approval(proposal)

    with factory() as session:
        applied = apply_reviewed_capture(session, repository, proposal, approval, apply=True)
        rerun = apply_reviewed_capture(session, repository, proposal, approval, apply=True)

        task = session.scalar(select(Task).where(Task.wiki_id == applied["task_wiki_id"]))
        assert task is not None
        assert task.title == "No priority supplied"
        assert task.priority == 0
        assert task.due_date is None
        assert rerun == {"status": "unchanged", "capture_id": proposal["capture_id"], "task_wiki_id": task.wiki_id}
    assert capture.read_text(encoding="utf-8").count("capture-receipt: cap-no-priority") == 1


def test_reviewed_scanner_proposal_rejects_stale_or_rebound_envelopes_before_source_mutation(tmp_path: Path) -> None:
    wiki, _capture, factory = _setup(tmp_path)
    repository = WikiRepository(wiki)
    capture, proposal = _scan_fixture_proposal(repository)
    approval = _scanner_approval(proposal)
    original = capture.read_text(encoding="utf-8")

    rebound = dict(proposal)
    rebound["target"] = {"type": "project", "id": "prj-other", "path": "01-Projects/other/index.md"}
    mismatched_approval = _scanner_approval({**proposal, "title": "Unreviewed replacement"})
    capture.write_text(original.replace("Follow up with supplier", "Changed after review"), encoding="utf-8")
    changed = capture.read_text(encoding="utf-8")
    invalid = [
        (proposal, approval, "source hash"),
        (rebound, approval, "approval"),
        (proposal, mismatched_approval, "approval"),
    ]

    for candidate, candidate_approval, message in invalid:
        with factory() as session, pytest.raises(CapturePromotionError, match=message):
            apply_reviewed_capture(session, repository, candidate, candidate_approval, apply=True)
        assert capture.read_text(encoding="utf-8") == changed
        assert repository.find_by_id("tsk-capture-cap-2026-08-23-scanned") is None


def test_reviewed_capture_apply_preflights_all_invalid_inputs_without_writes(tmp_path: Path) -> None:
    wiki, capture, factory = _setup(tmp_path)
    repository = WikiRepository(wiki)
    proposal = _proposal(capture)
    original = capture.read_text(encoding="utf-8")

    invalid_source_hash = _proposal(capture) | {"source_hash": "0" * 64}
    missing_project = _proposal(
        capture, target={"type": "project", "id": "prj-missing", "path": "01-Projects/missing/index.md"}
    )
    invalid = [
        (invalid_source_hash, _approval(invalid_source_hash), "source hash"),
        (
            _proposal(capture, target={"type": "inbox", "id": None, "path": "Changed"}),
            _approval(proposal),
            "approval",
        ),
        (proposal, None, "approval"),
        (missing_project, _approval(missing_project), "target"),
    ]
    for candidate, approval, message in invalid:
        with factory() as session, pytest.raises(CapturePromotionError, match=message):
            apply_reviewed_capture(session, repository, candidate, approval, apply=True)
            assert False, "unreachable"
        assert capture.read_text(encoding="utf-8") == original
        assert repository.list_records("task") == []


def test_reviewed_capture_rejects_duplicate_identity_before_source_mutation(tmp_path: Path) -> None:
    wiki, capture, factory = _setup(tmp_path)
    repository = WikiRepository(wiki)
    proposal = _proposal(capture)
    repository.write(
        "task",
        "Conflicting task",
        {"id": "tsk-capture-cap-2026-08-23-follow-up", "status": "open", "task_list": "Inbox"},
    )
    before = capture.read_text(encoding="utf-8")

    with factory() as session, pytest.raises(CapturePromotionError, match="identity"):
        apply_reviewed_capture(session, repository, proposal, _approval(proposal), apply=True)

    assert capture.read_text(encoding="utf-8") == before


def test_reviewed_capture_places_project_target_task_under_owner_path(tmp_path: Path) -> None:
    wiki, capture, factory = _setup(tmp_path)
    repository = WikiRepository(wiki)
    project = repository.write("project", "Home renovation", {"id": "prj-home", "status": "active"})
    proposal = _proposal(capture, target={"type": "project", "id": project.record_id, "path": project.path})

    with factory() as session:
        result = apply_reviewed_capture(session, repository, proposal, _approval(proposal), apply=True)

    record = repository.find_by_id(result["task_wiki_id"])
    assert record is not None
    assert record.path.startswith("01-Projects/home-renovation/tasks/")
    assert record.fields["capture_promotion"]["target"] == proposal["target"]
    assert record.fields["owner_type"] == "project"
    assert record.fields["owner_wiki_id"] == project.record_id


def test_reviewed_capture_reports_reconciliation_when_daily_receipt_conflicts_after_task_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wiki, capture, factory = _setup(tmp_path)
    repository = WikiRepository(wiki)
    proposal = _proposal(capture)
    original_create = capture_promotion.create_canonical_task

    def create_then_change_source(*args, **kwargs):
        task = original_create(*args, **kwargs)
        capture.write_text("# changed during promotion\n", encoding="utf-8")
        return task

    monkeypatch.setattr(capture_promotion, "create_canonical_task", create_then_change_source)
    with factory() as session, pytest.raises(CapturePromotionReconciliationRequired, match="reconciliation"):
        apply_reviewed_capture(session, repository, proposal, _approval(proposal), apply=True)

    assert repository.find_by_id("tsk-capture-cap-2026-08-23-follow-up") is not None
    assert "capture-receipt:" not in capture.read_text(encoding="utf-8")


def test_reviewed_capture_reports_reconciliation_after_task_source_write_projection_failure(tmp_path: Path) -> None:
    wiki, capture, factory = _setup(tmp_path)
    repository = WikiRepository(wiki)
    proposal = _proposal(capture)

    def fail_projection(session, _context, _instances):
        if any(isinstance(item, Task) for item in session.new):
            raise RuntimeError("simulated projection failure")

    event.listen(Session, "before_flush", fail_projection)
    try:
        with factory() as session, pytest.raises(CapturePromotionReconciliationRequired, match="reconciliation"):
            apply_reviewed_capture(session, repository, proposal, _approval(proposal), apply=True)
    finally:
        event.remove(Session, "before_flush", fail_projection)

    assert repository.find_by_id("tsk-capture-cap-2026-08-23-follow-up") is not None
    assert "capture-receipt:" not in capture.read_text(encoding="utf-8")


def test_review_record_is_deterministic_backlinked_and_idempotent(tmp_path: Path) -> None:
    wiki, capture, factory = _setup(tmp_path)
    repository = WikiRepository(wiki)
    source = repository.write("task", "Due task", {"id": "tsk-due", "status": "open", "task_list": "Inbox"})
    with factory() as session:
        session.add(
            Task(
                title="Due task",
                status="open",
                due_date=date(2026, 8, 22),
                task_list_id=1,
                wiki_id=source.record_id,
                wiki_path=source.path,
                wiki_hash=source.content_hash,
            )
        )
        session.commit()
        scan = {
            "unpromoted_captures": [{"capture_id": "cap-1", "source_path": capture.relative_to(wiki).as_posix()}],
            "inbox": ["tsk-due"],
            "stalled_owners": [{"owner_id": "prj-stalled", "reason": "no next action"}],
        }
        reconciliation = {"hash_conflicts": ["tsk-due"], "aligned": False}
        first = generate_review_record(
            session, repository, cadence="weekly", period="2026-W34", scan=scan, reconciliation=reconciliation
        )
        second = generate_review_record(
            session, repository, cadence="weekly", period="2026-W34", scan=scan, reconciliation=reconciliation
        )

    record = (wiki / first["path"]).read_text(encoding="utf-8")
    assert first == second
    assert first["path"] == "01-Projects/LifeOS/lifeos/reviews/weekly-2026-w34.md"
    assert "00-Daily/2026-08-23.md" in record
    assert "tsk-due" in record
    assert "overdue_or_due_next" in record
    assert "no next action" in record
    assert "hash_conflicts" in record


def test_monthly_review_record_uses_stable_month_path_for_empty_real_reports(tmp_path: Path) -> None:
    wiki, _capture, factory = _setup(tmp_path)
    with factory() as session:
        result = generate_review_record(
            session,
            WikiRepository(wiki),
            cadence="monthly",
            period="2026-08",
            scan={"proposals": [], "exceptions": []},
            reconciliation={"aligned": True},
        )

    assert result["path"] == "01-Projects/LifeOS/lifeos/reviews/monthly-2026-08.md"


def test_review_record_consumes_real_scan_and_reconciliation_reports_with_stable_backlinks(tmp_path: Path) -> None:
    wiki, _capture, factory = _setup(tmp_path)
    repository = WikiRepository(wiki)
    capture, proposal = _scan_fixture_proposal(repository)
    source_task = repository.write(
        "task",
        "Unprojected inbox task",
        {"id": "tsk-unprojected", "status": "open", "task_list": "Inbox", "owner_type": "inbox"},
        path="00-Inbox/tasks/unprojected-tsk-unprojected.md",
    )
    stalled_owner = repository.write("project", "Stalled project", {"id": "prj-stalled", "status": "active"})
    source_before = {
        path.relative_to(wiki).as_posix(): path.read_bytes()
        for path in wiki.rglob("*.md")
    }
    with factory() as session:
        scan = scan_daily_captures(repository, daily_root="Daily", start="2026-08-23", end="2026-08-23")
        reconciliation = reconcile_wiki_projection(session, repository)
        first = generate_review_record(
            session, repository, cadence="weekly", period="2026-W34", scan=scan, reconciliation=reconciliation
        )
        second = generate_review_record(
            session, repository, cadence="weekly", period="2026-W34", scan=scan, reconciliation=reconciliation
        )

    record = (wiki / first["path"]).read_text(encoding="utf-8")
    assert first == second
    assert str(proposal["source_path"]) in record
    assert str(proposal["capture_id"]) in record
    assert source_task.record_id in record
    assert source_task.path in record
    assert stalled_owner.path in record
    assert "unpromoted_captures" in record
    assert "inbox_items" in record
    assert "stalled_or_no_next_action_owners" in record
    assert "reconciliation_exceptions" in record
    assert capture.read_text(encoding="utf-8").count("capture-receipt:") == 0
    assert {
        path.relative_to(wiki).as_posix(): path.read_bytes()
        for path in wiki.rglob("*.md")
        if path.relative_to(wiki).as_posix() != first["path"]
    } == source_before


def test_nonprojected_markdown_write_refuses_symlink_target(tmp_path: Path) -> None:
    repository = WikiRepository(tmp_path / "wiki")
    target = repository.root / "safe.md"
    target.parent.mkdir(parents=True)
    target.write_text("# safe\n", encoding="utf-8")
    link = repository.root / "linked.md"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        repository.write_markdown("linked.md", "# unsafe\n")

    assert target.read_text(encoding="utf-8") == "# safe\n"


def test_promotion_cli_requires_apply_and_durable_approval_file(tmp_path: Path) -> None:
    wiki, _capture, _factory = _setup(tmp_path)
    capture, proposal = _scan_fixture_proposal(WikiRepository(wiki))
    proposal_path = tmp_path / "proposal.json"
    approval_path = tmp_path / "approval.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    approval_path.write_text(json.dumps(_scanner_approval(proposal)), encoding="utf-8")
    database = tmp_path / "lifeos.db"
    command = [
        sys.executable,
        "scripts/promote_capture.py",
        "--database",
        f"sqlite:///{database}",
        "--fixture-root",
        str(wiki),
        "--proposal-file",
        str(proposal_path),
        "--approval-file",
        str(approval_path),
    ]

    dry_run = subprocess.run(command, cwd=Path(__file__).parents[1], capture_output=True, text=True, check=True)
    applied = subprocess.run(
        command + ["--apply"], cwd=Path(__file__).parents[1], capture_output=True, text=True, check=True
    )

    assert json.loads(dry_run.stdout)["status"] == "dry_run"
    assert json.loads(applied.stdout)["status"] == "applied"
    assert WikiRepository(wiki).find_by_id("tsk-capture-cap-2026-08-23-scanned") is not None


def test_promotion_cli_rejects_legacy_ad_hoc_payload_before_mutation(tmp_path: Path) -> None:
    wiki, capture, _factory = _setup(tmp_path)
    proposal = {
        "capture_id": "cap-2026-08-23-legacy",
        "source_path": "00-Daily/2026-08-23.md",
        "source_hash": _sha256(capture),
        "target": {"owner_id": "inbox", "task_list": "Inbox"},
        "task": {"title": "Legacy ad hoc task"},
    }
    proposal_path = tmp_path / "proposal.json"
    approval_path = tmp_path / "approval.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    approval_path.write_text(json.dumps(_scanner_approval(proposal)), encoding="utf-8")
    source_before = capture.read_text(encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/promote_capture.py",
            "--database",
            f"sqlite:///{tmp_path / 'lifeos.db'}",
            "--fixture-root",
            str(wiki),
            "--proposal-file",
            str(proposal_path),
            "--approval-file",
            str(approval_path),
            "--apply",
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "source line" in result.stderr
    assert capture.read_text(encoding="utf-8") == source_before
    assert WikiRepository(wiki).list_records("task") == []


def test_promotion_cli_refuses_unmarked_fixture_root(tmp_path: Path) -> None:
    wiki, capture, _factory = _setup(tmp_path)
    (wiki / ".lifeos-fixture").unlink()
    proposal_path = tmp_path / "proposal.json"
    approval_path = tmp_path / "approval.json"
    proposal = _proposal(capture)
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    approval_path.write_text(json.dumps(_approval(proposal)), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/promote_capture.py",
            "--database",
            f"sqlite:///{tmp_path / 'lifeos.db'}",
            "--fixture-root",
            str(wiki),
            "--proposal-file",
            str(proposal_path),
            "--approval-file",
            str(approval_path),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "fixture marker" in result.stderr
