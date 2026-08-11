import sqlite3

from sqlalchemy import select

from lifeos.db import create_engine, create_session_factory
from lifeos.domain import AuditRecord, Task, TaskList
from lifeos.main import create_app
from scripts.backup_lifeos import backup_database
from scripts.verify_backup import verify_backup


def test_backup_restores_task_and_audit_history(tmp_path) -> None:
    source = tmp_path / "lifeos.db"
    backup = tmp_path / "backups" / "lifeos.db"
    restored = tmp_path / "restored.db"
    app = create_app(
        database_url=f"sqlite:///{source}",
        auth_username="brian",
        auth_password="password",
    )
    session_factory = app.state.session_factory
    with session_factory() as session:
        task_list = TaskList(name="Inbox")
        session.add(task_list)
        session.flush()
        task = Task(title="Back up LifeOS", task_list_id=task_list.id)
        session.add(task)
        session.flush()
        session.add(AuditRecord(entity_type="task", entity_id=task.id, action="created", actor="brian"))
        session.commit()

    result = backup_database(source, backup)
    assert result.exists()
    assert result.stat().st_size > 0

    with sqlite3.connect(restored) as destination, sqlite3.connect(backup) as origin:
        origin.backup(destination)
        destination.commit()

    assert verify_backup(restored) == {
        "tasks": 1,
        "audit_records": 1,
        "metric_definitions": 0,
        "metric_entries": 0,
        "routine_skips": 0,
        "goal_milestones": 0,
        "task_dependencies": 0,
    }
    engine = create_engine(f"sqlite:///{restored}")
    with create_session_factory(engine)() as session:
        assert session.scalar(select(Task).where(Task.title == "Back up LifeOS")) is not None
        assert session.scalar(select(AuditRecord).where(AuditRecord.action == "created")) is not None
