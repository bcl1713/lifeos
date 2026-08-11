from datetime import date

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import (
    Goal,
    Project,
    Routine,
    Task,
    TaskList,
)


def test_initialize_database_creates_core_schema_and_persists_relationships(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'lifeos.db'}")
    initialize_database(engine)
    session = create_session_factory(engine)()

    task_list = TaskList(name="Personal")
    goal = Goal(title="Build a sustainable routine")
    project = Project(title="LifeOS", goal=goal)
    routine = Routine(title="Morning review", cadence="daily", goal=goal)
    task = Task(
        title="Review today",
        task_list=task_list,
        goal=goal,
        project=project,
        routine=routine,
        due_date=date(2026, 8, 12),
    )
    session.add(task)
    session.commit()

    stored = session.query(Task).one()
    assert stored.title == "Review today"
    assert stored.task_list.name == "Personal"
    assert stored.goal.title == "Build a sustainable routine"
    assert stored.project.title == "LifeOS"
    assert stored.routine.cadence == "daily"
    assert stored.status == "open"
    assert stored.created_at is not None

    session.close()
    engine.dispose()
