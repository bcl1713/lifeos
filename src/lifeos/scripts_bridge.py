"""Bridge canonical wiki records into rebuildable LifeOS projections."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import json
from fastapi import HTTPException
from sqlalchemy import select

from lifeos.domain import Goal, GoalMilestone, Project, Routine, RoutineSkip, Task, TaskDependency, TaskList, WikiContextItem
from lifeos.wiki_links import resolve_wiki_link
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


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _value(record: WikiRecord, key: str) -> Any:
    value = record.fields.get(key)
    if isinstance(value, str) and value.startswith("["):
        return value
    return value


def _projection_identity(record_type: str, item: Any) -> str | None:
    return item.source_id if record_type == "area" else item.wiki_id


def _projection_hash(record_type: str, item: Any) -> str | None:
    return item.content_hash if record_type == "area" else item.wiki_hash


def _unresolved_relationships(records: list[WikiRecord]) -> list[dict[str, str]]:
    records_by_id = {record.record_id: record for record in records}
    singular = {
        "goal_wiki_id": "goal",
        "project_wiki_id": "project",
        "routine_wiki_id": "routine",
        "parent_wiki_id": "task",
    }
    unresolved: list[dict[str, str]] = []
    for record in records:
        relationships: list[tuple[str, str, str]] = []
        for field, expected_type in singular.items():
            target_id = _value(record, field)
            if target_id:
                relationships.append((field, str(target_id), expected_type))
        depends_on = _value(record, "depends_on") or []
        if isinstance(depends_on, list):
            relationships.extend(("depends_on", str(target_id), "task") for target_id in depends_on if target_id)
        for field, target_id, expected_type in relationships:
            target = records_by_id.get(target_id)
            if target is None or target.record_type != expected_type:
                unresolved.append(
                    {
                        "id": record.record_id,
                        "field": field,
                        "target_id": target_id,
                        "expected_type": expected_type,
                    }
                )
    return sorted(unresolved, key=lambda value: (value["id"], value["field"], value["target_id"]))


def _invalid_task_owners(records: list[WikiRecord]) -> list[dict[str, str]]:
    records_by_id = {record.record_id: record for record in records}
    invalid: list[dict[str, str]] = []
    for record in records:
        if record.record_type != "task":
            continue
        owner_type = _value(record, "owner_type")
        owner_wiki_id = _value(record, "owner_wiki_id")
        if owner_type is None and owner_wiki_id is None:
            continue
        detail = {"id": record.record_id, "owner_type": str(owner_type or ""), "owner_wiki_id": str(owner_wiki_id or "")}
        if owner_type == "inbox" and owner_wiki_id is None and _value(record, "task_list") == "Inbox":
            continue
        if owner_type in {"project", "area"} and owner_wiki_id:
            owner = records_by_id.get(str(owner_wiki_id))
            if owner is not None and owner.record_type == owner_type:
                continue
            detail["reason"] = "owner type mismatch" if owner is not None else "owner is missing"
        else:
            detail["reason"] = "owner fields are incomplete or Inbox is invalid"
        invalid.append(detail)
    return sorted(invalid, key=lambda value: value["id"])


def reconcile_wiki_projection(session, repository: WikiRepository) -> dict[str, object]:
    """Report projection alignment without mutating either source."""
    records = repository.list_records()
    unresolved_relationships = _unresolved_relationships(records)
    invalid_task_owners = _invalid_task_owners(records)
    models = {"project": Project, "goal": Goal, "routine": Routine, "task": Task}

    source_by_id: dict[str, list[WikiRecord]] = {}
    for record in records:
        source_by_id.setdefault(record.record_id, []).append(record)

    projection_rows: list[tuple[str, Any]] = []
    for record_type, model in models.items():
        projection_rows.extend((record_type, item) for item in session.scalars(select(model)))
    projection_rows.extend(
        ("area", item)
        for item in session.scalars(select(WikiContextItem).where(WikiContextItem.source_type == "area"))
    )

    projection_by_id: dict[str, list[tuple[str, Any]]] = {}
    missing_identity: list[str] = []
    projection_by_path: dict[str, list[str]] = {}
    for record_type, item in projection_rows:
        label = f"{record_type}:{item.id}"
        identity = _projection_identity(record_type, item)
        if identity:
            projection_by_id.setdefault(identity, []).append((record_type, item))
        else:
            missing_identity.append(label)
        if item.wiki_path:
            projection_by_path.setdefault(item.wiki_path, []).append(label)

    source_ids = set(source_by_id)
    projection_ids = set(projection_by_id)
    matched_ids = sorted(source_ids & projection_ids)
    missing_projection = sorted(source_ids - projection_ids)
    orphaned_projection = sorted(projection_ids - source_ids)
    duplicate_source_ids = {
        record_id: sorted(record.path for record in grouped)
        for record_id, grouped in sorted(source_by_id.items())
        if len(grouped) > 1
    }
    duplicate_projection_ids = {
        record_id: sorted(record_type for record_type, _item in grouped)
        for record_id, grouped in sorted(projection_by_id.items())
        if len(grouped) > 1
    }
    duplicate_projection_paths = {
        path: sorted(labels) for path, labels in sorted(projection_by_path.items()) if len(labels) > 1
    }
    invalid_links: list[dict[str, str]] = []
    for record_type, item in projection_rows:
        if not item.wiki_path:
            continue
        try:
            link = resolve_wiki_link(item.wiki_path, repository.root)
        except HTTPException as exc:
            link = {"link_status": "invalid", "diagnostic": str(exc.detail)}
        if link["link_status"] != "valid":
            invalid_links.append(
                {
                    "id": _projection_identity(record_type, item) or f"{record_type}:{item.id}",
                    "path": item.wiki_path,
                    "status": str(link["link_status"]),
                    "diagnostic": str(link["diagnostic"]),
                }
            )

    hash_conflicts: set[str] = set()
    path_conflicts: set[str] = set()
    type_conflicts: list[dict[str, str]] = []
    for record_id in matched_ids:
        source_records = source_by_id[record_id]
        source_types = {record.record_type for record in source_records}
        for projection_type, item in projection_by_id[record_id]:
            typed_sources = [record for record in source_records if record.record_type == projection_type]
            if not typed_sources:
                type_conflicts.append(
                    {"id": record_id, "projection_type": projection_type, "source_type": sorted(source_types)[0]}
                )
                continue
            source_paths = {record.path for record in typed_sources}
            if item.wiki_path not in source_paths:
                path_conflicts.add(record_id)
            matching_path = next((record for record in typed_sources if record.path == item.wiki_path), typed_sources[0])
            projection_hash = _projection_hash(projection_type, item)
            if projection_hash and projection_hash != matching_path.content_hash:
                hash_conflicts.add(record_id)

    discrepancies = (
        missing_projection,
        orphaned_projection,
        duplicate_source_ids,
        duplicate_projection_ids,
        duplicate_projection_paths,
        missing_identity,
        type_conflicts,
        path_conflicts,
        hash_conflicts,
        invalid_links,
        unresolved_relationships,
        invalid_task_owners,
    )
    return {
        "wiki_records": len(records),
        "projection_records": len(projection_rows),
        "matched_ids": matched_ids,
        "missing_projection": missing_projection,
        "orphaned_projection": orphaned_projection,
        "duplicate_source_ids": duplicate_source_ids,
        "duplicate_projection_ids": duplicate_projection_ids,
        "duplicate_projection_paths": duplicate_projection_paths,
        "missing_identity": sorted(missing_identity),
        "type_conflicts": sorted(type_conflicts, key=lambda value: (value["id"], value["projection_type"])),
        "path_conflicts": sorted(path_conflicts),
        "hash_conflicts": sorted(hash_conflicts),
        "invalid_links": sorted(invalid_links, key=lambda value: (value["id"], value["path"])),
        "unresolved_relationships": unresolved_relationships,
        "invalid_task_owners": invalid_task_owners,
        "aligned": not any(discrepancies),
    }


def sync_wiki_projection(session, repository: WikiRepository) -> dict[str, int]:
    records = repository.list_records()
    source_paths_by_id: dict[str, list[str]] = {}
    for record in records:
        source_paths_by_id.setdefault(record.record_id, []).append(record.path)
    duplicate_ids = {
        record_id: sorted(paths) for record_id, paths in source_paths_by_id.items() if len(paths) > 1
    }
    if duplicate_ids:
        detail = "; ".join(f"{record_id}: {', '.join(paths)}" for record_id, paths in sorted(duplicate_ids.items()))
        raise ValueError(f"duplicate canonical wiki IDs: {detail}")
    unresolved_relationships = _unresolved_relationships(records)
    if unresolved_relationships:
        detail = "; ".join(
            f"{value['id']}.{value['field']} -> {value['target_id']} ({value['expected_type']})"
            for value in unresolved_relationships
        )
        raise ValueError(f"unresolved canonical relationships: {detail}")
    invalid_task_owners = _invalid_task_owners(records)
    if invalid_task_owners:
        detail = "; ".join(
            f"{value['id']} ({value['reason']})" for value in invalid_task_owners
        )
        raise ValueError(f"invalid task owners: {detail}")

    counts = {"created": 0, "updated": 0, "stale": 0, "unchanged": 0}
    canonical_area_ids = {record.record_id for record in records if record.record_type == "area"}
    for record in records:
        if record.record_type == "area":
            item = session.scalar(select(WikiContextItem).where(WikiContextItem.source_id == record.record_id))
            aliases = _value(record, "aliases")
            if not isinstance(aliases, list):
                aliases = [aliases] if aliases else []
            summary = next(
                (line.strip() for line in record.body.splitlines() if line.strip() and not line.startswith("#")),
                "",
            )
            modified_at = datetime.fromtimestamp((repository.root / record.path).stat().st_mtime, timezone.utc)
            if item is None:
                item = WikiContextItem(
                    source_type="area",
                    source_id=record.record_id,
                    title=record.title,
                    wiki_path=record.path,
                    wiki_url=f"/sources/wiki/{record.path}",
                    content_hash=record.content_hash,
                    modified_at=modified_at,
                )
                session.add(item)
                counts["created"] += 1
            elif item.content_hash == record.content_hash and not item.stale:
                counts["unchanged"] += 1
                continue
            else:
                counts["updated"] += 1
            item.source_type = "area"
            item.title = record.title
            item.wiki_path = record.path
            item.wiki_url = f"/sources/wiki/{record.path}"
            item.status = str(_value(record, "status") or "active")
            item.aliases = json.dumps(aliases, sort_keys=True)
            item.summary = summary[:1000]
            item.content_hash = record.content_hash
            item.modified_at = modified_at
            item.stale = False
        elif record.record_type == "project":
            item = session.scalar(select(Project).where(Project.wiki_id == record.record_id))
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
            item.collaborators = _value(record, "collaborators")
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
            list_name = str(_value(record, "task_list") or "Inbox")
            task_list = session.scalar(select(TaskList).where(TaskList.name == list_name))
            if task_list is None:
                task_list = TaskList(name=list_name)
                session.add(task_list)
                session.flush()
            item = session.scalar(select(Routine).where(Routine.wiki_id == record.record_id))
            if item is None:
                item = Routine(title=record.title, cadence=str(_value(record, "cadence") or "weekly"), next_run_date=_date(_value(record, "next_run_date")) or date.today(), task_list_id=task_list.id)
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
            item.minimum_occurrences = _value(record, "minimum_occurrences") or None
            item.frequency_window_days = _value(record, "frequency_window_days") or None
            item.task_list_id = task_list.id
            item.wiki_id, item.wiki_path, item.wiki_hash = record.record_id, record.path, record.content_hash
        elif record.record_type == "task":
            list_name = str(_value(record, "task_list") or "Inbox")
            task_list = session.scalar(select(TaskList).where(TaskList.name == list_name))
            if task_list is None:
                task_list = TaskList(name=list_name)
                session.add(task_list)
                session.flush()
            item = session.scalar(select(Task).where(Task.wiki_id == record.record_id))
            if item is None:
                item = Task(title=record.title, task_list_id=task_list.id)
                session.add(item)
                counts["created"] += 1
            elif item.wiki_hash == record.content_hash:
                counts["unchanged"] += 1
                continue
            else:
                counts["updated"] += 1
            item.title = record.title
            item.task_list_id = task_list.id
            item.status = str(_value(record, "status") or item.status)
            item.notes = _value(record, "notes")
            item.priority = int(_value(record, "priority") or item.priority or 0)
            tags = _value(record, "tags")
            if isinstance(tags, list):
                item.tags = json.dumps(tags, sort_keys=True)
            item.source_ref = _value(record, "source_ref")
            item.due_date = _date(_value(record, "due_date"))
            item.occurrence_key = _value(record, "occurrence_key") or None
            item.owner_wiki_id = _value(record, "owner_wiki_id") or None
            item.owner_type = _value(record, "owner_type") or None
            item.wiki_id, item.wiki_path, item.wiki_hash = record.record_id, record.path, record.content_hash
    for item in session.scalars(select(WikiContextItem).where(WikiContextItem.source_type == "area")):
        if item.source_id not in canonical_area_ids and not item.stale:
            item.stale = True
            counts["stale"] += 1
    session.flush()
    goals_by_wiki_id = {item.wiki_id: item for item in session.scalars(select(Goal)) if item.wiki_id}
    projects_by_wiki_id = {item.wiki_id: item for item in session.scalars(select(Project)) if item.wiki_id}
    routines_by_wiki_id = {item.wiki_id: item for item in session.scalars(select(Routine)) if item.wiki_id}
    tasks_by_wiki_id = {item.wiki_id: item for item in session.scalars(select(Task)) if item.wiki_id}
    for record in records:
        if record.record_type == "project":
            project = projects_by_wiki_id.get(record.record_id)
            goal = goals_by_wiki_id.get(str(_value(record, "goal_wiki_id") or ""))
            if project is not None:
                project.goal_id = goal.id if goal else None
        elif record.record_type == "routine":
            routine = routines_by_wiki_id.get(record.record_id)
            goal = goals_by_wiki_id.get(str(_value(record, "goal_wiki_id") or ""))
            if routine is not None:
                routine.goal_id = goal.id if goal else None
        elif record.record_type == "task":
            task = tasks_by_wiki_id.get(record.record_id)
            if task is None:
                continue
            goal = goals_by_wiki_id.get(str(_value(record, "goal_wiki_id") or ""))
            project = projects_by_wiki_id.get(str(_value(record, "project_wiki_id") or ""))
            routine = routines_by_wiki_id.get(str(_value(record, "routine_wiki_id") or ""))
            parent = tasks_by_wiki_id.get(str(_value(record, "parent_wiki_id") or ""))
            task.goal_id = goal.id if goal else None
            task.project_id = project.id if project else None
            task.routine_id = routine.id if routine else None
            task.parent_id = parent.id if parent else None
    session.flush()
    for record in (item for item in records if item.record_type == "goal"):
        goal = session.scalar(select(Goal).where(Goal.wiki_id == record.record_id))
        if goal is None:
            continue
        for milestone in list(goal.milestones):
            session.delete(milestone)
        for value in _value(record, "milestones") or []:
            if not isinstance(value, dict) or not value.get("title"):
                continue
            session.add(
                GoalMilestone(
                    goal_id=goal.id,
                    title=str(value["title"]),
                    status=str(value.get("status") or "open"),
                    due_date=_date(value.get("due_date")),
                    completed_at=_datetime(value.get("completed_at")),
                )
            )
    session.flush()
    for record in (item for item in records if item.record_type == "routine"):
        routine = session.scalar(select(Routine).where(Routine.wiki_id == record.record_id))
        if routine is None:
            continue
        existing_skips = {skip.scheduled_date: skip for skip in routine.skips}
        desired_skips = {}
        for value in _value(record, "skips") or []:
            if not isinstance(value, dict):
                continue
            scheduled_date = _date(value.get("scheduled_date"))
            if scheduled_date is not None:
                desired_skips[scheduled_date] = value.get("reason")
        for scheduled_date, skip in existing_skips.items():
            if scheduled_date not in desired_skips:
                session.delete(skip)
            else:
                skip.reason = desired_skips[scheduled_date]
        for scheduled_date, reason in desired_skips.items():
            if scheduled_date not in existing_skips:
                session.add(RoutineSkip(routine_id=routine.id, scheduled_date=scheduled_date, reason=reason))
    session.flush()
    for record in (item for item in records if item.record_type == "task"):
        task = session.scalar(select(Task).where(Task.wiki_id == record.record_id))
        if task is None:
            continue
        desired_ids = _value(record, "depends_on") or []
        if not isinstance(desired_ids, list):
            desired_ids = []
        desired_tasks = list(session.scalars(select(Task).where(Task.wiki_id.in_(desired_ids)))) if desired_ids else []
        desired_local_ids = {item.id for item in desired_tasks}
        current_edges = list(
            session.scalars(select(TaskDependency).where(TaskDependency.task_id == task.id))
        )
        for edge in current_edges:
            if edge.depends_on_task_id not in desired_local_ids:
                session.delete(edge)
        current_local_ids = {edge.depends_on_task_id for edge in current_edges}
        for prerequisite_id in desired_local_ids - current_local_ids:
            session.add(TaskDependency(task_id=task.id, depends_on_task_id=prerequisite_id))
    session.commit()
    return counts
