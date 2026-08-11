import json

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import Task, TaskList
from scripts.export_lifeos import export_database
from scripts.restore_lifeos import restore_database
from scripts.retain_lifeos_backups import retention_plan


def test_export_contains_all_tables_and_rows(tmp_path) -> None:
    database = tmp_path / "lifeos.db"
    engine = create_engine(f"sqlite:///{database}")
    initialize_database(engine)
    with create_session_factory(engine)() as session:
        task_list = TaskList(name="Inbox")
        session.add(task_list)
        session.flush()
        session.add(Task(title="Export me", task_list_id=task_list.id))
        session.commit()
    output = tmp_path / "export.json"
    counts = export_database(database, output)
    payload = json.loads(output.read_text())
    assert counts["tasks"] == 1
    assert payload["format"] == "lifeos-export-v1"
    assert payload["tables"]["tasks"][0]["title"] == "Export me"


def test_retention_keeps_latest_daily_and_monthly_backups(tmp_path) -> None:
    for stamp in ("20260811T120000Z", "20260810T120000Z", "20260731T120000Z", "20260701T120000Z", "20250601T120000Z"):
        (tmp_path / f"lifeos-{stamp}.db").write_bytes(b"backup")
    keep, remove = retention_plan(tmp_path, daily=2, monthly=2)
    assert {path.name for path in keep} == {
        "lifeos-20260811T120000Z.db",
        "lifeos-20260810T120000Z.db",
        "lifeos-20260731T120000Z.db",
    }
    assert [path.name for path in remove] == ["lifeos-20250601T120000Z.db", "lifeos-20260701T120000Z.db"]


def test_restore_round_trip_preserves_task_and_audit_counts(tmp_path) -> None:
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"
    restored = tmp_path / "restored.db"
    engine = create_engine(f"sqlite:///{source}")
    initialize_database(engine)
    with create_session_factory(engine)() as session:
        task_list = TaskList(name="Inbox")
        session.add(task_list)
        session.flush()
        session.add(Task(title="Restore me", task_list_id=task_list.id))
        session.commit()
    from scripts.backup_lifeos import backup_database

    backup_database(source, backup)
    restore_database(backup, restored)
    with create_session_factory(create_engine(f"sqlite:///{restored}"))() as session:
        assert session.query(Task).count() == 1
        assert session.query(TaskList).count() == 1
