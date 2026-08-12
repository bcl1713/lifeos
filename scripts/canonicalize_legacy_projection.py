#!/usr/bin/env python3
"""Canonicalize legacy LifeOS projection rows into wiki Markdown.

Dry-run is the default. Use --apply only after verified SQLite and wiki backups.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos.db import create_engine, create_session_factory
from lifeos.domain import Goal, Project, Routine, Task, TaskDependency
from lifeos.wiki_store import WikiRepository, slugify

_MODELS = (("goal", Goal, "goal", "goals"), ("project", Project, "prj", "projects"), ("routine", Routine, "rtn", "routines"), ("task", Task, "tsk", "tasks"))


def _source(table: str, row_id: int) -> dict[str, Any]:
    return {"table": table, "row_id": row_id}


def _identity_maps(session: Session) -> tuple[dict[int, str], dict[int, str], dict[int, str], dict[int, str]]:
    maps: list[dict[int, str]] = []
    for _record_type, model, prefix, _table in _MODELS:
        maps.append({item.id: item.wiki_id or f"{prefix}-legacy-{item.id}" for item in session.scalars(select(model))})
    return maps[0], maps[1], maps[2], maps[3]


def _base_fields(item: Any, excluded: set[str]) -> dict[str, Any]:
    return {
        column.name: getattr(item, column.name)
        for column in item.__table__.columns
        if column.name not in excluded
    }


def _record_fields(
    session: Session,
    record_type: str,
    item: Any,
    identity: str,
    table: str,
    goal_ids: dict[int, str],
    project_ids: dict[int, str],
    routine_ids: dict[int, str],
    task_ids: dict[int, str],
) -> dict[str, Any]:
    excluded = {"id", "title", "created_at", "updated_at", "wiki_id", "wiki_path", "wiki_hash"}
    fields = _base_fields(item, excluded)
    fields["id"] = identity
    fields["migration_source"] = _source(table, item.id)
    fields["migrated_from_projection"] = True
    if record_type == "goal":
        fields["milestones"] = [
            {
                "id": f"mil-legacy-{milestone.id}",
                "title": milestone.title,
                "status": milestone.status,
                "due_date": milestone.due_date.isoformat() if milestone.due_date else None,
                "completed_at": milestone.completed_at.isoformat() if milestone.completed_at else None,
            }
            for milestone in item.milestones
        ]
    elif record_type == "project":
        fields.pop("goal_id", None)
        fields["goal_wiki_id"] = goal_ids.get(item.goal_id) if item.goal_id else None
    elif record_type == "routine":
        fields.pop("task_list_id", None)
        fields.pop("goal_id", None)
        fields["task_list"] = item.task_list.name
        fields["goal_wiki_id"] = goal_ids.get(item.goal_id) if item.goal_id else None
        fields["skips"] = [
            {"scheduled_date": skip.scheduled_date.isoformat(), "reason": skip.reason}
            for skip in item.skips
        ]
    elif record_type == "task":
        for key in ("task_list_id", "goal_id", "project_id", "routine_id", "parent_id"):
            fields.pop(key, None)
        fields["task_list"] = item.task_list.name
        fields["goal_wiki_id"] = goal_ids.get(item.goal_id) if item.goal_id else None
        fields["project_wiki_id"] = project_ids.get(item.project_id) if item.project_id else None
        fields["routine_wiki_id"] = routine_ids.get(item.routine_id) if item.routine_id else None
        fields["parent_wiki_id"] = task_ids.get(item.parent_id) if item.parent_id else None
        dependency_ids = session.scalars(
            select(TaskDependency.depends_on_task_id)
            .where(TaskDependency.task_id == item.id)
            .order_by(TaskDependency.id)
        )
        fields["depends_on"] = [task_ids[dependency_id] for dependency_id in dependency_ids]
        try:
            fields["tags"] = json.loads(item.tags or "[]")
        except json.JSONDecodeError:
            fields["tags"] = [item.tags] if item.tags else []
    return fields


def _legacy_project_path(item: Project, identity: str) -> str:
    return f"01-Projects/{slugify(item.title)}-{identity}/index.md"


def canonicalize_legacy_projection(
    session: Session,
    repository: WikiRepository,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    rows: dict[str, list[Any]] = {
        record_type: list(session.scalars(select(model).order_by(model.id)))
        for record_type, model, _prefix, _table in _MODELS
    }
    planned = {record_type: sum(not item.wiki_id for item in items) for record_type, items in rows.items()}
    missing = [
        (record_type, item, prefix, table)
        for record_type, model, prefix, table in _MODELS
        for item in rows[record_type]
        if not item.wiki_id
    ]
    goal_ids, project_ids, routine_ids, task_ids = _identity_maps(session)
    maps = {"goal": goal_ids, "project": project_ids, "routine": routine_ids, "task": task_ids}

    conflicts: list[str] = []
    existing_by_identity: dict[str, Any] = {}
    for record_type, item, prefix, table in missing:
        identity = maps[record_type][item.id]
        existing = repository.find_by_id(identity)
        if existing is not None:
            if existing.record_type != record_type or existing.fields.get("migration_source") != _source(table, item.id):
                conflicts.append(f"{identity}: canonical identity is already owned by another source")
            else:
                existing_by_identity[identity] = existing
    if conflicts:
        raise ValueError("canonicalization preflight failed: " + "; ".join(conflicts))

    result: dict[str, Any] = {
        "apply": apply,
        "planned": planned,
        "created": {record_type: 0 for record_type, _model, _prefix, _table in _MODELS},
        "adopted": 0,
        "unchanged": sum(bool(item.wiki_id) and bool((repository.find_by_id(item.wiki_id))) for items in rows.values() for item in items),
        "remaining_missing_identity": sum(planned.values()),
    }
    if not apply:
        return result

    try:
        for record_type, item, _prefix, table in missing:
            identity = maps[record_type][item.id]
            existing = existing_by_identity.get(identity)
            if existing is None:
                fields = _record_fields(
                    session,
                    record_type,
                    item,
                    identity,
                    table,
                    goal_ids,
                    project_ids,
                    routine_ids,
                    task_ids,
                )
                path = _legacy_project_path(item, identity) if record_type == "project" else None
                record = repository.write(record_type, item.title, fields, path=path)
                result["created"][record_type] += 1
            else:
                record = existing
                result["adopted"] += 1
            item.wiki_id = record.record_id
            item.wiki_path = record.path
            item.wiki_hash = record.content_hash
        session.commit()
    except Exception:
        session.rollback()
        raise

    result["remaining_missing_identity"] = sum(
        len(list(session.scalars(select(model.id).where((model.wiki_id.is_(None)) | (model.wiki_id == "")))))
        for _record_type, model, _prefix, _table in _MODELS
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="sqlite:///./data/lifeos.db")
    parser.add_argument("--wiki-root", default="/wiki")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    engine = create_engine(args.database)
    factory = create_session_factory(engine)
    with factory() as session:
        result = canonicalize_legacy_projection(session, WikiRepository(args.wiki_root), apply=args.apply)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
