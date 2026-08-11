import json
from datetime import date

from sqlalchemy import select

from lifeos.db import create_engine, create_session_factory
from lifeos.domain import AuditRecord, Task
from lifeos.google_tasks_migration import import_to_database, select_for_migration, to_lifeos_record


def test_migration_selects_open_and_recent_completed_records() -> None:
    records = [
        {
            "list_id": "a",
            "list_title": "My Tasks",
            "id": "1",
            "title": "Open",
            "notes": "",
            "status": "needsAction",
            "due": "",
            "updated": "2020-01-01T00:00:00Z",
        },
        {
            "list_id": "a",
            "list_title": "My Tasks",
            "id": "2",
            "title": "Recent",
            "notes": "note",
            "status": "completed",
            "due": "2026-01-01T00:00:00Z",
            "updated": "2026-01-01T00:00:00Z",
        },
        {
            "list_id": "a",
            "list_title": "My Tasks",
            "id": "3",
            "title": "Old",
            "notes": "",
            "status": "completed",
            "due": "",
            "updated": "2024-01-01T00:00:00Z",
        },
    ]
    selected, excluded = select_for_migration(records, date(2026, 8, 11))
    assert [item["id"] for item in selected] == ["1", "2"]
    assert excluded == 1
    mapped = to_lifeos_record(selected[1])
    assert mapped["source"] == "google-tasks:a:2"
    assert mapped["notes"].startswith("Source: google-tasks:a:2")
    assert mapped["due_date"] == "2026-01-01"
    assert mapped["status"] == "completed"


def test_staging_import_is_idempotent_and_audited(tmp_path) -> None:
    export = tmp_path / "export.json"
    export.write_text(
        json.dumps(
            [
                {
                    "list_id": "a",
                    "list_title": "My Tasks",
                    "tasks": [
                        {
                            "id": "1",
                            "title": "Imported",
                            "notes": "n",
                            "status": "needsAction",
                            "due": "",
                            "updated": "2026-08-01T00:00:00Z",
                        }
                    ],
                }
            ]
        )
    )
    from lifeos.google_tasks_migration import load_export

    mapped = [to_lifeos_record(item) for item in load_export(export)]
    db = tmp_path / "staging.db"
    assert import_to_database(mapped, db) == {"created": 1, "skipped": 0}
    assert import_to_database(mapped, db) == {"created": 0, "skipped": 1}
    engine = create_engine(f"sqlite:///{db}")
    with create_session_factory(engine)() as session:
        assert session.scalar(select(Task).where(Task.title == "Imported")) is not None
        assert session.scalar(select(AuditRecord).where(AuditRecord.action == "migrated")) is not None
