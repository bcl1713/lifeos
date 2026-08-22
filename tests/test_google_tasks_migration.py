import json
import hashlib
import subprocess
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select
import pytest

from lifeos.db import create_engine, create_session_factory
from lifeos.domain import AuditRecord, Task, TaskList
from lifeos.google_tasks_migration import import_to_database, select_for_migration, to_lifeos_record
from lifeos.wiki_store import WikiConflictError, WikiRepository


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
                        },
                        {
                            "id": "2",
                            "title": "Imported completed",
                            "notes": "done",
                            "status": "completed",
                            "due": "",
                            "updated": "2026-08-02T00:00:00Z",
                        }
                    ],
                }
            ]
        )
    )
    from lifeos.google_tasks_migration import load_export

    mapped = [to_lifeos_record(item) for item in load_export(export)]
    db = tmp_path / "staging.db"
    wiki = tmp_path / "wiki"
    assert import_to_database(mapped, db, wiki) == {"created": 2, "skipped": 0}
    assert import_to_database(mapped, db, wiki) == {"created": 0, "skipped": 2}
    engine = create_engine(f"sqlite:///{db}")
    with create_session_factory(engine)() as session:
        task = session.scalar(select(Task).where(Task.title == "Imported"))
        assert task is not None
        assert task.wiki_id
        assert task.wiki_path
        assert session.get(TaskList, task.task_list_id).name == "Inbox"
        completed = session.scalar(select(Task).where(Task.title == "Imported completed"))
        assert completed is not None
        assert completed.status == "completed"
        assert len(list(session.scalars(select(AuditRecord).where(AuditRecord.action == "migrated")))) == 2
    record = WikiRepository(wiki).find_by_id(task.wiki_id)
    assert record is not None
    assert record.fields["status"] == "open"
    assert record.fields["notes"].startswith("Source: google-tasks:a:1")
    assert record.fields["task_list"] == "Inbox"
    assert record.fields["owner_type"] == "inbox"
    assert record.fields["owner_wiki_id"] is None
    completed_record = WikiRepository(wiki).find_by_id(completed.wiki_id)
    assert completed_record is not None
    assert completed_record.fields["status"] == "completed"


def test_cli_requires_wiki_root_for_database_import(tmp_path) -> None:
    export = tmp_path / "export.json"
    export.write_text("[]")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/migrate_google_tasks.py",
            str(export),
            "--staging-database",
            str(tmp_path / "staging.db"),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--wiki-root is required with --staging-database" in result.stderr
    assert not (tmp_path / "staging.db").exists()


def test_import_rejects_unrelated_canonical_task_with_deterministic_id(tmp_path) -> None:
    source = "google-tasks:a:collision"
    canonical_id = f"tsk-google-{hashlib.sha256(source.encode()).hexdigest()[:16]}"
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    occupied = repository.write(
        "task",
        "Unrelated canonical task",
        {"id": canonical_id, "status": "open", "task_list": "Inbox", "source_ref": "manual:unrelated"},
    )
    occupied_path = wiki / occupied.path
    before = occupied_path.read_bytes()
    record = {
        "source": source,
        "list_name": "My Tasks",
        "title": "Imported collision",
        "notes": f"Source: {source}",
        "due_date": None,
        "status": "open",
        "source_updated": "2026-08-12T00:00:00Z",
    }

    with pytest.raises(WikiConflictError, match="owned by another source"):
        import_to_database([record], tmp_path / "staging.db", wiki)

    assert occupied_path.read_bytes() == before
    engine = create_engine(f"sqlite:///{tmp_path / 'staging.db'}")
    with create_session_factory(engine)() as session:
        assert session.scalar(select(Task)) is None


def test_import_resumes_same_source_canonical_record_after_projection_loss(tmp_path) -> None:
    source = "google-tasks:a:resume"
    canonical_id = f"tsk-google-{hashlib.sha256(source.encode()).hexdigest()[:16]}"
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    existing = repository.write(
        "task",
        "Imported before projection failure",
        {
            "id": canonical_id,
            "status": "open",
            "task_list": "My Tasks",
            "source_ref": source,
            "notes": f"Source: {source}",
        },
    )
    record = {
        "source": source,
        "list_name": "My Tasks",
        "title": "Resumed import",
        "notes": f"Source: {source}\nRecovered",
        "due_date": None,
        "status": "completed",
        "source_updated": "2026-08-12T00:00:00Z",
    }

    assert import_to_database([record], tmp_path / "staging.db", wiki) == {"created": 1, "skipped": 0}

    resumed = repository.find_by_id(canonical_id)
    assert resumed is not None
    assert resumed.path == existing.path
    assert resumed.fields["source_ref"] == source
    assert resumed.fields["status"] == "completed"
    engine = create_engine(f"sqlite:///{tmp_path / 'staging.db'}")
    with create_session_factory(engine)() as session:
        task = session.scalar(select(Task).where(Task.wiki_id == canonical_id))
        assert task is not None
        assert task.status == "completed"
        assert task.source_ref == source


def test_import_does_not_skip_for_unrelated_projection_notes_marker(tmp_path) -> None:
    source = "google-tasks:a:projection-note-collision"
    canonical_id = f"tsk-google-{hashlib.sha256(source.encode()).hexdigest()[:16]}"
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    occupied = repository.write(
        "task",
        "Unrelated canonical task",
        {"id": canonical_id, "status": "open", "task_list": "Inbox", "source_ref": "manual:unrelated"},
    )
    occupied_path = wiki / occupied.path
    before = occupied_path.read_bytes()
    db = tmp_path / "staging.db"
    engine = create_engine(f"sqlite:///{db}")
    from lifeos.db import initialize_database
    from lifeos.domain import TaskList

    initialize_database(engine)
    with create_session_factory(engine)() as session:
        task_list = TaskList(name="Inbox")
        session.add(task_list)
        session.flush()
        session.add(
            Task(
                title="Unrelated projection row",
                notes=f"A coincidental note containing {source}",
                source_ref="manual:projection",
                task_list_id=task_list.id,
            )
        )
        session.commit()
    record = {
        "source": source,
        "list_name": "My Tasks",
        "title": "Imported collision",
        "notes": f"Source: {source}",
        "due_date": None,
        "status": "open",
        "source_updated": "2026-08-12T00:00:00Z",
    }

    with pytest.raises(WikiConflictError, match="owned by another source"):
        import_to_database([record], db, wiki)

    assert occupied_path.read_bytes() == before
    with create_session_factory(engine)() as session:
        tasks = list(session.scalars(select(Task)))
        assert len(tasks) == 1
        assert tasks[0].source_ref == "manual:projection"


@pytest.mark.parametrize("with_canonical_mismatch", [False, True])
def test_import_rejects_projection_identity_requiring_reconciliation(tmp_path, with_canonical_mismatch: bool) -> None:
    source = "google-tasks:a:projection-reconciliation"
    canonical_id = f"tsk-google-{hashlib.sha256(source.encode()).hexdigest()[:16]}"
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    existing = None
    if with_canonical_mismatch:
        existing = repository.write(
            "task",
            "Canonical Google task",
            {"id": canonical_id, "status": "open", "task_list": "My Tasks", "source_ref": source},
        )
    db = tmp_path / "staging.db"
    engine = create_engine(f"sqlite:///{db}")
    from lifeos.db import initialize_database
    from lifeos.domain import TaskList

    initialize_database(engine)
    with create_session_factory(engine)() as session:
        task_list = TaskList(name="My Tasks")
        session.add(task_list)
        session.flush()
        session.add(
            Task(
                title="Stale imported projection",
                notes=f"Source: {source}",
                source_ref=source,
                task_list_id=task_list.id,
                wiki_id="tsk-wrong-projection-id" if existing else canonical_id,
                wiki_path=existing.path if existing else "01-Projects/LifeOS/lifeos/tasks/missing.md",
            )
        )
        session.commit()
    before = {record.path: (wiki / record.path).read_bytes() for record in repository.list_records()}
    record = {
        "source": source,
        "list_name": "My Tasks",
        "title": "Incoming Google task",
        "notes": f"Source: {source}",
        "due_date": None,
        "status": "open",
        "source_updated": "2026-08-12T00:00:00Z",
    }

    with pytest.raises(WikiConflictError, match="projection identity requires reconciliation"):
        import_to_database([record], db, wiki)

    assert {path: (wiki / path).read_bytes() for path in before} == before
    found = repository.find_by_id(canonical_id)
    if existing is None:
        assert found is None
    else:
        assert found is not None
        assert (found.record_id, found.path, found.content_hash) == (
            existing.record_id,
            existing.path,
            existing.content_hash,
        )


def test_import_preflights_entire_batch_before_any_canonical_write(tmp_path) -> None:
    conflicting_source = "google-tasks:a:batch-conflict"
    conflicting_id = f"tsk-google-{hashlib.sha256(conflicting_source.encode()).hexdigest()[:16]}"
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    occupied = repository.write(
        "task",
        "Unrelated canonical owner",
        {"id": conflicting_id, "status": "open", "task_list": "Inbox", "source_ref": "manual:owner"},
    )
    before = {record.path: (wiki / record.path).read_bytes() for record in repository.list_records()}
    records = [
        {
            "source": "google-tasks:a:valid-first",
            "list_name": "My Tasks",
            "title": "Valid first record",
            "notes": "Source: google-tasks:a:valid-first",
            "due_date": None,
            "status": "open",
            "source_updated": "2026-08-12T00:00:00Z",
        },
        {
            "source": conflicting_source,
            "list_name": "My Tasks",
            "title": "Conflicting second record",
            "notes": f"Source: {conflicting_source}",
            "due_date": None,
            "status": "open",
            "source_updated": "2026-08-12T00:00:00Z",
        },
    ]
    db = tmp_path / "staging.db"

    with pytest.raises(WikiConflictError, match="owned by another source"):
        import_to_database(records, db, wiki)

    assert {path: (wiki / path).read_bytes() for path in before} == before
    assert repository.find_by_id(
        f"tsk-google-{hashlib.sha256(records[0]['source'].encode()).hexdigest()[:16]}"
    ) is None
    assert (wiki / occupied.path).read_bytes() == before[occupied.path]
    engine = create_engine(f"sqlite:///{db}")
    with create_session_factory(engine)() as session:
        assert session.scalar(select(Task)) is None
        assert session.scalar(select(AuditRecord)) is None


def test_import_rejects_duplicate_canonical_id_before_idempotent_skip(tmp_path) -> None:
    source = "google-tasks:a:duplicate-canonical"
    canonical_id = f"tsk-google-{hashlib.sha256(source.encode()).hexdigest()[:16]}"
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    exact_owner = repository.write(
        "task",
        "Exact Google owner",
        {"id": canonical_id, "status": "open", "task_list": "My Tasks", "source_ref": source},
    )
    foreign_owner = repository.write(
        "task",
        "Foreign owner",
        {"id": canonical_id, "status": "open", "task_list": "My Tasks", "source_ref": "manual:foreign"},
        path="01-Projects/LifeOS/lifeos/tasks/foreign-duplicate-owner.md",
    )
    assert exact_owner.path != foreign_owner.path
    before = {record.path: (wiki / record.path).read_bytes() for record in repository.list_records()}
    db = tmp_path / "staging.db"
    engine = create_engine(f"sqlite:///{db}")
    from lifeos.db import initialize_database
    from lifeos.domain import TaskList

    initialize_database(engine)
    with create_session_factory(engine)() as session:
        task_list = TaskList(name="My Tasks")
        session.add(task_list)
        session.flush()
        session.add(
            Task(
                title="Exact Google owner",
                notes=f"Source: {source}",
                source_ref=source,
                task_list_id=task_list.id,
                wiki_id=exact_owner.record_id,
                wiki_path=exact_owner.path,
                wiki_hash=exact_owner.content_hash,
            )
        )
        session.commit()
    record = {
        "source": source,
        "list_name": "My Tasks",
        "title": "Exact Google owner",
        "notes": f"Source: {source}",
        "due_date": None,
        "status": "open",
        "source_updated": "2026-08-12T00:00:00Z",
    }

    with pytest.raises(WikiConflictError, match="duplicate canonical identity"):
        import_to_database([record], db, wiki)

    assert {path: (wiki / path).read_bytes() for path in before} == before
    with create_session_factory(engine)() as session:
        tasks = list(session.scalars(select(Task)))
        assert len(tasks) == 1
        assert tasks[0].wiki_path == exact_owner.path
        assert session.scalar(select(AuditRecord)) is None
