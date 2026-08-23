"""Fixture-scoped, explicitly approved capture promotion and review records."""
from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import date
from pathlib import Path
from typing import Any, Literal, Mapping

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos.domain import Task, TaskList
from lifeos.task_api import TaskCreate, create_canonical_task
from lifeos.wiki_store import WikiConflictError, WikiRecord, WikiRepository, render_frontmatter, slugify


class CapturePromotionError(ValueError):
    """Raised before any source mutation when a reviewed proposal is invalid."""


class CapturePromotionReconciliationRequired(RuntimeError):
    """A task source write succeeded but its projection did not."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _proposal_fingerprint(proposal: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(dict(proposal)).encode("utf-8")).hexdigest()


def _source_file(repository: WikiRepository, source_path: str) -> Path:
    if not source_path.endswith(".md"):
        raise CapturePromotionError("source path must be Markdown")
    root = repository.root
    relative = Path(source_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise CapturePromotionError("source path escapes wiki root")
    raw = root / relative
    for parent in (raw, *raw.parents):
        if parent == root.parent:
            break
        if parent.is_symlink():
            raise CapturePromotionError("source path must not traverse symlinks")
        if parent == root:
            break
    target = raw.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise CapturePromotionError("source path escapes wiki root") from exc
    if not target.is_file():
        raise CapturePromotionError("source path is missing")
    return target


def _required_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapturePromotionError(f"{name} is required")
    return value.strip()


def _validate_approval(proposal: Mapping[str, Any], approval: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(approval, Mapping):
        raise CapturePromotionError("approval record is required")
    _required_string(approval.get("approval_id"), "approval id")
    if "source_line" in proposal:
        if _canonical_json(approval.get("approved_proposal")) != _canonical_json(proposal):
            raise CapturePromotionError("approval does not match the reviewed scanner proposal")
        if approval.get("proposal_fingerprint") != _proposal_fingerprint(proposal):
            raise CapturePromotionError("approval fingerprint does not match the reviewed scanner proposal")
        return dict(approval)
    for key in ("capture_id", "source_path", "source_hash"):
        if approval.get(key) != proposal.get(key):
            raise CapturePromotionError(f"approval {key.replace('_', ' ')} does not match proposal")
    if _canonical_json(approval.get("target")) != _canonical_json(proposal.get("target")):
        raise CapturePromotionError("approval target does not match proposal")
    return dict(approval)


def _target_owner(
    repository: WikiRepository, target: Mapping[str, Any]
) -> tuple[str, Literal["project", "area", "inbox"], str | None]:
    owner_id = _required_string(target.get("owner_id"), "target owner")
    task_list = _required_string(target.get("task_list"), "target task list")
    if owner_id == "inbox":
        return task_list, "inbox", None
    owner = repository.find_by_id(owner_id)
    if owner is None:
        raise CapturePromotionError("target owner is not a canonical Project, Area, or Inbox")
    if owner.record_type == "project":
        return task_list, "project", owner.record_id
    if owner.record_type == "area":
        return task_list, "area", owner.record_id
    raise CapturePromotionError("target owner is not a canonical Project, Area, or Inbox")


def _scanner_target_owner(
    repository: WikiRepository, target: Mapping[str, Any]
) -> tuple[str, Literal["project", "area", "inbox"], str | None]:
    """Bind an unmodified scanner target to the current canonical owner."""
    target_type = _required_string(target.get("type"), "target type")
    target_path = _required_string(target.get("path"), "target path")
    target_id = target.get("id")
    if target_type == "inbox":
        if target_id is not None or target_path != "00-Inbox":
            raise CapturePromotionError("target does not match the canonical Inbox")
        return "Inbox", "inbox", None
    if target_type not in {"project", "area"} or not isinstance(target_id, str):
        raise CapturePromotionError("target does not resolve to a canonical Project or Area")
    owner = repository.find_by_id(target_id)
    if owner is None or owner.record_type != target_type or owner.path != target_path:
        raise CapturePromotionError("target does not match the reviewed canonical owner")
    return "Inbox", "project" if target_type == "project" else "area", owner.record_id


def _scanner_task_values(proposal: Mapping[str, Any]) -> dict[str, Any]:
    due = proposal.get("due")
    if due is not None:
        try:
            due = date.fromisoformat(_required_string(due, "task due"))
        except ValueError as exc:
            raise CapturePromotionError("task due must use YYYY-MM-DD") from exc
    priority = proposal.get("priority")
    if priority is None:
        priority = 0
    if not isinstance(priority, int) or isinstance(priority, bool) or priority not in range(4):
        raise CapturePromotionError("task priority must be between 0 and 3")
    return {"title": _required_string(proposal.get("title"), "task title"), "due_date": due, "priority": priority}


def _scanner_source_hash(source_text: str, source_line: Any) -> str:
    if not isinstance(source_line, int) or isinstance(source_line, bool) or source_line < 1:
        raise CapturePromotionError("source line is required")
    lines = source_text.splitlines()
    if source_line > len(lines):
        raise CapturePromotionError("source line is outside the daily note")
    return hashlib.sha256(lines[source_line - 1].encode("utf-8")).hexdigest()


def _receipt(capture_id: str, task_wiki_id: str, fingerprint: str) -> str:
    return (
        "\n<!-- lifeos-capture-receipt\n"
        f"capture-receipt: {capture_id}\n"
        f"task-wiki-id: {task_wiki_id}\n"
        f"proposal-fingerprint: {fingerprint}\n"
        "-->\n"
    )


def apply_reviewed_capture(
    session: Session,
    repository: WikiRepository,
    proposal: Mapping[str, Any],
    approval: Mapping[str, Any] | None,
    *,
    apply: bool,
) -> dict[str, str]:
    """Apply one reviewed fixture capture, never mutating without ``apply=True``."""
    if apply is not True:
        raise CapturePromotionError("explicit apply is required")
    capture_id = _required_string(proposal.get("capture_id"), "capture id")
    source_path = _required_string(proposal.get("source_path"), "source path")
    source_hash = _required_string(proposal.get("source_hash"), "source hash")
    if len(source_hash) != 64 or any(character not in "0123456789abcdef" for character in source_hash):
        raise CapturePromotionError("source hash must be a SHA-256 hex digest")
    target = proposal.get("target")
    if not isinstance(target, Mapping):
        raise CapturePromotionError("target is required")
    approval_record = _validate_approval(proposal, approval)
    source = _source_file(repository, source_path)
    fingerprint = _proposal_fingerprint(proposal)
    task_wiki_id = f"tsk-capture-{slugify(capture_id)}"
    source_bytes = source.read_bytes()
    source_text = source_bytes.decode("utf-8")
    scanner_proposal = "source_line" in proposal
    if scanner_proposal:
        task_values = _scanner_task_values(proposal)
        actual_hash = _scanner_source_hash(source_text, proposal["source_line"])
        task_list_name, owner_type, owner_wiki_id = _scanner_target_owner(repository, target)
    else:
        task_values = proposal.get("task")
        if not isinstance(task_values, Mapping):
            raise CapturePromotionError("task is required")
        actual_hash = hashlib.sha256(source_bytes).hexdigest()
        task_list_name, owner_type, owner_wiki_id = _target_owner(repository, target)
    existing = repository.find_by_id(task_wiki_id)
    if existing is not None and existing.fields.get("capture_promotion", {}).get("capture_id") == capture_id:
        if _receipt(capture_id, task_wiki_id, fingerprint).strip() in source_text:
            return {"status": "unchanged", "capture_id": capture_id, "task_wiki_id": task_wiki_id}
        raise CapturePromotionError("capture identity exists without a matching receipt")
    if existing is not None:
        raise CapturePromotionError("capture task identity is already owned")
    if actual_hash != source_hash:
        raise CapturePromotionError("source hash changed since proposal review")
    task_list = session.scalar(select(TaskList).where(TaskList.name == task_list_name))
    if task_list is None:
        raise CapturePromotionError("target task list does not exist")
    session.info["wiki_repository"] = repository
    try:
        task = create_canonical_task(
            session,
            TaskCreate(
                title=_required_string(task_values.get("title"), "task title"),
                task_list_id=task_list.id,
                notes=task_values.get("notes"),
                priority=int(task_values.get("priority", 0)),
                tags=list(task_values.get("tags", [])),
                source_ref=f"capture:{capture_id}",
                due_date=task_values.get("due_date"),
                owner_type=owner_type,
                owner_wiki_id=owner_wiki_id,
            ),
            "capture-promotion",
            record_id=task_wiki_id,
            canonical_metadata={
                "capture_promotion": {
                    "capture_id": capture_id,
                    "source_path": source_path,
                    "source_hash": source_hash,
                    "target": dict(target),
                    "approval_id": approval_record["approval_id"],
                    "proposal_fingerprint": fingerprint,
                },
                **(
                    {
                        "daily_capture_id": capture_id,
                        "daily_capture_source_hash": source_hash,
                        "daily_capture_source_path": source_path,
                    }
                    if scanner_proposal
                    else {}
                ),
            },
            audit_action="capture_promoted",
            audit_payload={"capture_id": capture_id, "approval_id": approval_record["approval_id"]},
        )
    except HTTPException as exc:
        if exc.status_code == 503:
            raise CapturePromotionReconciliationRequired(
                "canonical task source was written; reconciliation is required"
            ) from exc
        raise
    try:
        repository.write_markdown(
            source_path,
            source_text + _receipt(capture_id, task.wiki_id, fingerprint),
            expected_hash=hashlib.sha256(source_bytes).hexdigest(),
        )
    except WikiConflictError as exc:
        raise CapturePromotionReconciliationRequired(
            "canonical task source was written; daily capture receipt requires reconciliation"
        ) from exc
    return {"status": "applied", "capture_id": capture_id, "task_wiki_id": task.wiki_id}


def _period_end(cadence: str, period: str) -> date:
    if cadence == "weekly":
        try:
            year, week = period.split("-W")
            return date.fromisocalendar(int(year), int(week), 7)
        except ValueError as exc:
            raise CapturePromotionError("weekly period must use YYYY-Www") from exc
    if cadence == "monthly":
        try:
            year, month = (int(value) for value in period.split("-"))
            return date(year, month, monthrange(year, month)[1])
        except ValueError as exc:
            raise CapturePromotionError("monthly period must use YYYY-MM") from exc
    raise CapturePromotionError("cadence must be weekly or monthly")


_RECONCILIATION_EXCEPTION_KEYS = {
    "authority_conflicts",
    "duplicate_projection_ids",
    "duplicate_projection_paths",
    "duplicate_source_ids",
    "hash_conflicts",
    "invalid_links",
    "invalid_task_owners",
    "missing_identity",
    "missing_projection",
    "orphaned_projection",
    "path_conflicts",
    "shadowed_archive_ids",
    "type_conflicts",
    "unresolved_relationships",
}


def _record_backlink(record: WikiRecord) -> dict[str, str]:
    return {"wiki_id": record.record_id, "source_path": record.path, "title": record.title}


def _reconciliation_backlinks(value: Any, records_by_id: Mapping[str, WikiRecord]) -> Any:
    if isinstance(value, str):
        record = records_by_id.get(value)
        return _record_backlink(record) if record is not None else value
    if isinstance(value, list):
        return [_reconciliation_backlinks(item, records_by_id) for item in value]
    if isinstance(value, Mapping):
        result = {str(key): _reconciliation_backlinks(item, records_by_id) for key, item in value.items()}
        record_id = result.get("id")
        if isinstance(record_id, str) and (record := records_by_id.get(record_id)) is not None:
            result.setdefault("source_path", record.path)
        return result
    return value


def _review_source_records(repository: WikiRepository) -> list[WikiRecord]:
    try:
        return repository.authoritative_records()
    except ValueError:
        return repository.list_records()


def generate_review_record(
    session: Session,
    repository: WikiRepository,
    *,
    cadence: str,
    period: str,
    scan: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
) -> dict[str, str]:
    """Render an idempotent canonical review document from scan and projection state."""
    period_end = _period_end(cadence, period)
    records = _review_source_records(repository)
    records_by_id = {record.record_id: record for record in records}
    inbox = [
        _record_backlink(record)
        for record in records
        if record.record_type == "task"
        and record.fields.get("status", "open") == "open"
        and record.fields.get("owner_type") == "inbox"
        and record.fields.get("task_list") == "Inbox"
    ]
    owner_records = [
        record
        for record in records
        if record.record_type in {"project", "area"} and record.fields.get("status", "active") == "active"
    ]
    open_owner_ids = {
        str(record.fields["owner_wiki_id"])
        for record in records
        if record.record_type == "task"
        and record.fields.get("status", "open") == "open"
        and record.fields.get("owner_wiki_id")
    }
    stalled = [
        {**_record_backlink(record), "reason": "no open next action"}
        for record in owner_records
        if record.record_id not in open_owner_ids
    ]
    legacy_stalled = scan.get("stalled_owners", [])
    if not isinstance(legacy_stalled, list):
        raise CapturePromotionError("scan stalled owners must be a list")
    due = [
        {
            "wiki_id": task.wiki_id,
            "source_path": task.wiki_path,
            "title": task.title,
            "due_date": task.due_date.isoformat(),
        }
        for task in session.scalars(select(Task).where(Task.status == "open", Task.due_date.is_not(None)))
        if task.due_date and task.due_date <= period_end
    ]
    proposals = scan.get("proposals", scan.get("unpromoted_captures", []))
    if not isinstance(proposals, list):
        raise CapturePromotionError("scan proposals must be a list")
    evidence = {
        "unpromoted_captures": sorted(proposals, key=_canonical_json),
        "inbox_items": sorted(inbox, key=_canonical_json),
        "overdue_or_due_next": sorted(due, key=_canonical_json),
        "stalled_or_no_next_action_owners": sorted([*stalled, *legacy_stalled], key=_canonical_json),
        "reconciliation_exceptions": {
            key: _reconciliation_backlinks(reconciliation[key], records_by_id)
            for key in sorted(reconciliation)
            if key in _RECONCILIATION_EXCEPTION_KEYS and reconciliation[key]
        },
    }
    path = f"01-Projects/LifeOS/lifeos/reviews/{cadence}-{period.lower()}.md"
    fields = {
        "schema_version": "1",
        "type": "review_record",
        "id": f"review-{cadence}-{period.lower()}",
        "cadence": cadence,
        "period": period,
        "source_backlinks": evidence,
    }
    body = f"# {cadence.title()} review {period}\n\n```json\n{json.dumps(evidence, indent=2, sort_keys=True)}\n```\n"
    content = render_frontmatter(fields, body)
    content_hash = repository.write_markdown(path, content)
    return {"path": path, "content_hash": content_hash}
