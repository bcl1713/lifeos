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
from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import Task, TaskList
from lifeos.scripts_bridge import reconcile_wiki_projection
from lifeos.wiki_store import WikiRepository


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _proposal(capture: Path, *, target: dict[str, str] | None = None) -> dict[str, object]:
    return {
        "capture_id": "cap-2026-08-23-follow-up",
        "source_path": "00-Daily/2026-08-23.md",
        "source_hash": _sha256(capture),
        "target": target or {"owner_id": "inbox", "task_list": "Inbox"},
        "task": {"title": "Follow up with supplier", "notes": "Reviewed capture", "priority": 2, "tags": ["follow-up"]},
    }


def _approval(proposal: dict[str, object]) -> dict[str, object]:
    return {
        "approval_id": "apr-2026-08-23-01",
        "capture_id": proposal["capture_id"],
        "source_path": proposal["source_path"],
        "source_hash": proposal["source_hash"],
        "target": proposal["target"],
    }


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
        assert repository.find_by_id(task.wiki_id).fields["capture_promotion"]["approval_id"] == "apr-2026-08-23-01"
        assert capture.read_text(encoding="utf-8").count("capture-receipt: cap-2026-08-23-follow-up") == 1
        assert reconcile_wiki_projection(session, repository)["aligned"] is True


def test_reviewed_capture_apply_preflights_all_invalid_inputs_without_writes(tmp_path: Path) -> None:
    wiki, capture, factory = _setup(tmp_path)
    repository = WikiRepository(wiki)
    proposal = _proposal(capture)
    original = capture.read_text(encoding="utf-8")

    invalid = [
        (_proposal(capture) | {"source_hash": "0" * 64}, _approval(proposal), "source hash"),
        (
            _proposal(capture, target={"owner_id": "inbox", "task_list": "Changed"}),
            _approval(proposal),
            "approval target",
        ),
        (proposal, None, "approval"),
        (
            _proposal(capture, target={"owner_id": "prj-missing", "task_list": "Inbox"}),
            _approval(_proposal(capture, target={"owner_id": "prj-missing", "task_list": "Inbox"})),
            "owner",
        ),
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
    proposal = _proposal(capture, target={"owner_id": project.record_id, "task_list": "Inbox"})

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


def test_monthly_review_record_uses_stable_month_path(tmp_path: Path) -> None:
    wiki, _capture, factory = _setup(tmp_path)
    with factory() as session:
        result = generate_review_record(
            session,
            WikiRepository(wiki),
            cadence="monthly",
            period="2026-08",
            scan={"unpromoted_captures": [], "inbox": [], "stalled_owners": []},
            reconciliation={"aligned": True},
        )

    assert result["path"] == "01-Projects/LifeOS/lifeos/reviews/monthly-2026-08.md"


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
    wiki, capture, factory = _setup(tmp_path)
    proposal = _proposal(capture)
    proposal_path = tmp_path / "proposal.json"
    approval_path = tmp_path / "approval.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
    approval_path.write_text(json.dumps(_approval(proposal)), encoding="utf-8")
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
    assert WikiRepository(wiki).find_by_id("tsk-capture-cap-2026-08-23-follow-up") is not None


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
