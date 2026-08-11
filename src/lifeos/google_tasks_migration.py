import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import AuditRecord, Task, TaskList


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


def import_to_database(records: list[dict], database: Path) -> dict[str, int]:
    engine = create_engine(f"sqlite:///{database}")
    initialize_database(engine)
    factory = create_session_factory(engine)
    created = skipped = 0
    with factory() as session:
        lists: dict[str, TaskList] = {}
        for record in records:
            list_name = record["list_name"]
            task_list = lists.get(list_name) or session.scalar(select(TaskList).where(TaskList.name == list_name))
            if task_list is None:
                task_list = TaskList(name=list_name)
                session.add(task_list)
                session.flush()
            lists[list_name] = task_list
            marker = record["source"]
            if session.scalar(select(Task).where(Task.notes.like(f"%{marker}%"))) is not None:
                skipped += 1
                continue
            task = Task(
                title=record["title"],
                notes=record["notes"],
                status=record["status"],
                due_date=date.fromisoformat(record["due_date"]) if record["due_date"] else None,
                task_list_id=task_list.id,
            )
            session.add(task)
            session.flush()
            session.add(
                AuditRecord(
                    entity_type="task",
                    entity_id=task.id,
                    action="migrated",
                    actor="google-tasks-migration",
                    payload=json.dumps({"source": record["source"], "source_updated": record["source_updated"]}),
                )
            )
            created += 1
        session.commit()
    return {"created": created, "skipped": skipped}
