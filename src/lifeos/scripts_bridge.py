"""Bridge canonical wiki records into rebuildable LifeOS projections."""
from __future__ import annotations

from datetime import date
from typing import Any

import json
from sqlalchemy import select

from lifeos.domain import Goal, Project, Routine, Task, TaskList
from lifeos.wiki_store import WikiRepository, WikiRecord


def _date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _value(record: WikiRecord, key: str) -> Any:
    value = record.fields.get(key)
    if isinstance(value, str) and value.startswith("["):
        return value
    return value


def reconcile_wiki_projection(session, repository: WikiRepository) -> dict[str, object]:
    """Report projection alignment without mutating either source."""
    records = {record.record_id: record for record in repository.list_records()}
    models = {"project": Project, "goal": Goal, "routine": Routine, "task": Task}
    projection: dict[str, Any] = {}
    for record_type, model in models.items():
        for item in session.scalars(select(model)):
            if item.wiki_id:
                projection[item.wiki_id] = item
    missing_projection = sorted(record_id for record_id in records if record_id not in projection)
    orphaned_projection = sorted(item.wiki_id for item in projection.values() if item.wiki_id not in records)
    hash_conflicts = sorted(
        record_id for record_id, item in projection.items()
        if record_id in records and item.wiki_hash and item.wiki_hash != records[record_id].content_hash
    )
    return {
        "wiki_records": len(records),
        "projection_records": len(projection),
        "missing_projection": missing_projection,
        "orphaned_projection": orphaned_projection,
        "hash_conflicts": hash_conflicts,
        "aligned": not (missing_projection or orphaned_projection or hash_conflicts),
    }


def sync_wiki_projection(session, repository: WikiRepository) -> dict[str, int]:
    counts = {"created": 0, "updated": 0, "stale": 0, "unchanged": 0}
    for record in repository.list_records():
        if record.record_type == "project":
            item = session.scalar(select(Project).where(Project.wiki_id == record.record_id))
            if item is None:
                item = session.scalar(select(Project).where(Project.title == record.title, Project.wiki_id.is_(None)))
            if item is None:
                item = Project(title=record.title)
                session.add(item)
                counts["created"] += 1
            elif item.wiki_hash == record.content_hash:
                counts["unchanged"] += 1
                continue
            else:
                counts["updated"] += 1
            item.title = record.title
            item.status = str(_value(record, "status") or item.status)
            item.owner = _value(record, "owner")
            item.scope = _value(record, "scope")
            item.non_goals = _value(record, "non_goals")
            item.risks = _value(record, "risks")
            item.deadline = _date(_value(record, "deadline"))
            item.review_trigger = _value(record, "review_trigger")
            item.source_refs = _value(record, "source_refs")
            item.wiki_id, item.wiki_path, item.wiki_hash = record.record_id, record.path, record.content_hash
        elif record.record_type == "goal":
            item = session.scalar(select(Goal).where(Goal.wiki_id == record.record_id))
            if item is None:
                item = session.scalar(select(Goal).where(Goal.title == record.title, Goal.wiki_id.is_(None)))
            if item is None:
                item = Goal(title=record.title)
                session.add(item)
                counts["created"] += 1
            elif item.wiki_hash == record.content_hash:
                counts["unchanged"] += 1
                continue
            else:
                counts["updated"] += 1
            for field in ("status", "outcome", "baseline", "target", "rationale", "constraints", "review_cadence", "adjustment_trigger"):
                value = _value(record, field)
                if value is not None:
                    setattr(item, field, value)
            item.review_date = _date(_value(record, "review_date"))
            item.wiki_id, item.wiki_path, item.wiki_hash = record.record_id, record.path, record.content_hash
        elif record.record_type == "routine":
            lists = list(session.scalars(select(TaskList).order_by(TaskList.id)))
            if not lists:
                lists = [TaskList(name="Inbox")]
                session.add(lists[0])
                session.flush()
            item = session.scalar(select(Routine).where(Routine.wiki_id == record.record_id))
            if item is None:
                item = session.scalar(select(Routine).where(Routine.title == record.title, Routine.wiki_id.is_(None)))
            if item is None:
                item = Routine(title=record.title, cadence=str(_value(record, "cadence") or "weekly"), next_run_date=_date(_value(record, "next_run_date")) or date.today(), task_list_id=lists[0].id)
                session.add(item)
                counts["created"] += 1
            elif item.wiki_hash == record.content_hash:
                counts["unchanged"] += 1
                continue
            else:
                counts["updated"] += 1
            item.cadence = str(_value(record, "cadence") or item.cadence)
            item.status = str(_value(record, "status") or item.status)
            item.next_run_date = _date(_value(record, "next_run_date")) or item.next_run_date
            item.wiki_id, item.wiki_path, item.wiki_hash = record.record_id, record.path, record.content_hash
        elif record.record_type == "task":
            lists = list(session.scalars(select(TaskList).order_by(TaskList.id)))
            if not lists:
                lists = [TaskList(name="Inbox")]
                session.add(lists[0])
                session.flush()
            item = session.scalar(select(Task).where(Task.wiki_id == record.record_id))
            if item is None:
                item = session.scalar(select(Task).where(Task.title == record.title, Task.wiki_id.is_(None)))
            if item is None:
                item = Task(title=record.title, task_list_id=lists[0].id)
                session.add(item)
                counts["created"] += 1
            elif item.wiki_hash == record.content_hash:
                counts["unchanged"] += 1
                continue
            else:
                counts["updated"] += 1
            item.title = record.title
            item.status = str(_value(record, "status") or item.status)
            item.notes = _value(record, "notes")
            item.priority = int(_value(record, "priority") or item.priority)
            tags = _value(record, "tags")
            if isinstance(tags, list):
                item.tags = json.dumps(tags, sort_keys=True)
            item.source_ref = _value(record, "source_ref")
            item.due_date = _date(_value(record, "due_date"))
            item.wiki_id, item.wiki_path, item.wiki_hash = record.record_id, record.path, record.content_hash
    session.commit()
    return counts
