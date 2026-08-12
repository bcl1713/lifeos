import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import Task, TaskList
from lifeos.task_api import TaskCreate, create_canonical_task
from lifeos.wiki_store import WikiConflictError, WikiRepository


def load_export(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    return [
        {
            "list_id": item["list_id"],
            "list_title": item["list_title"],
            "id": task["id"],
            "title": task.get("title", "").strip(),
            "notes": task.get("notes") or "",
            "status": task.get("status", "needsAction"),
            "due": task.get("due") or "",
            "updated": task.get("updated") or "",
        }
        for item in data
        for task in item.get("tasks", [])
        if task.get("title", "").strip()
    ]


def select_for_migration(records: list[dict], as_of: date) -> tuple[list[dict], int]:
    cutoff = datetime.combine(as_of - timedelta(days=365), datetime.min.time(), tzinfo=timezone.utc)
    selected = []
    excluded_completed = 0
    for record in records:
        if record["status"] != "completed":
            selected.append(record)
            continue
        updated = datetime.fromisoformat(record["updated"].replace("Z", "+00:00"))
        if updated >= cutoff:
            selected.append(record)
        else:
            excluded_completed += 1
    return selected, excluded_completed


def to_lifeos_record(record: dict) -> dict:
    due_date = record["due"][:10] if record["due"] else None
    source = f"google-tasks:{record['list_id']}:{record['id']}"
    marker = f"Source: {source}"
    notes = f"{marker}\n{record['notes']}" if record["notes"] else marker
    return {
        "source": source,
        "list_name": record["list_title"],
        "title": record["title"],
        "notes": notes,
        "due_date": due_date,
        "status": "completed" if record["status"] == "completed" else "open",
        "source_updated": record["updated"],
    }


def import_to_database(records: list[dict], database: Path, wiki_root: Path) -> dict[str, int]:
    engine = create_engine(f"sqlite:///{database}")
    initialize_database(engine)
    factory = create_session_factory(engine)
    created = skipped = 0
    with factory() as session:
        session.info["wiki_repository"] = WikiRepository(wiki_root)
        repository: WikiRepository = session.info["wiki_repository"]
        preflight: list[tuple[dict, str, object | None, bool]] = []
        seen_sources: set[str] = set()
        seen_ids: set[str] = set()
        canonical_by_id: dict[str, list[object]] = {}
        for canonical_record in repository.list_records():
            canonical_by_id.setdefault(canonical_record.record_id, []).append(canonical_record)
        for record in records:
            source = record["source"]
            canonical_id = f"tsk-google-{hashlib.sha256(source.encode()).hexdigest()[:16]}"
            if source in seen_sources or canonical_id in seen_ids:
                raise WikiConflictError("Google Tasks import batch contains duplicate canonical identity")
            seen_sources.add(source)
            seen_ids.add(canonical_id)
            canonical_matches = canonical_by_id.get(canonical_id, [])
            if len(canonical_matches) > 1:
                raise WikiConflictError("Google Tasks import found duplicate canonical identity")
            existing = canonical_matches[0] if canonical_matches else None
            if existing is not None and (
                existing.record_type != "task" or existing.fields.get("source_ref") != source
            ):
                raise WikiConflictError("Canonical import identity is owned by another source")
            projected = list(session.scalars(select(Task).where(Task.source_ref == source)))
            if projected and (
                existing is None
                or len(projected) != 1
                or projected[0].wiki_id != existing.record_id
                or projected[0].wiki_path != existing.path
            ):
                raise WikiConflictError("Google Tasks projection identity requires reconciliation")
            preflight.append((record, canonical_id, existing, bool(projected)))

        lists: dict[str, TaskList] = {}
        for record, canonical_id, existing, already_projected in preflight:
            if already_projected:
                skipped += 1
                continue
            list_name = record["list_name"]
            task_list = lists.get(list_name) or session.scalar(select(TaskList).where(TaskList.name == list_name))
            if task_list is None:
                task_list = TaskList(name=list_name)
                session.add(task_list)
                session.flush()
            lists[list_name] = task_list
            create_canonical_task(
                session,
                TaskCreate(
                    title=record["title"],
                    notes=record["notes"],
                    source_ref=record["source"],
                    due_date=date.fromisoformat(record["due_date"]) if record["due_date"] else None,
                    task_list_id=task_list.id,
                ),
                "google-tasks-migration",
                record_id=canonical_id,
                audit_payload={"source": record["source"], "source_updated": record["source_updated"]},
                audit_action="migrated",
                initial_status=record["status"],
                expected_hash=existing.content_hash if existing is not None else None,
                commit=False,
            )
            created += 1
        session.commit()
    return {"created": created, "skipped": skipped}
