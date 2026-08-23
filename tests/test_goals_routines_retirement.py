from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import Goal, Project, Routine, Task, TaskList
from lifeos.legacy_retirement import legacy_retirement_report
from lifeos.main import create_app
from lifeos.scheduler import generate_due_once
from lifeos.wiki_store import WikiRepository


def test_goals_and_routines_are_deprecated_without_active_api_or_navigation(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(tmp_path / "wiki"),
    )
    client = TestClient(app, follow_redirects=False)
    client.post("/auth/login", json={"username": "brian", "password": "password"})

    for response in (
        client.get("/api/goals"),
        client.post("/api/goals", json={"title": "Retired goal"}),
        client.get("/api/routines"),
        client.post("/api/routines", json={"title": "Retired routine"}),
        client.get("/goals"),
        client.get("/routines"),
        client.post("/ui/goals", data={"title": "Retired goal"}),
        client.post("/ui/routines", data={"title": "Retired routine"}),
    ):
        assert response.status_code == 410
        assert response.json()["detail"]["code"] == "legacy_domain_retired"

    home = client.get("/")
    assert 'href="/goals"' not in home.text
    assert 'href="/routines"' not in home.text


def test_legacy_retirement_report_is_dry_run_idempotent_and_maps_owner_local_recurrence(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    repository.write("project", "Home", {"id": "prj-home", "status": "active"})
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        inbox = TaskList(name="Inbox")
        project_list = TaskList(name="Projects")
        project = Project(title="Home", wiki_id="prj-home")
        goal = Goal(title="Legacy outcome")
        session.add_all([inbox, project_list, project, goal])
        session.flush()
        routine = Routine(
            title="Water plants",
            cadence="weekly",
            next_run_date=date(2026, 8, 24),
            minimum_occurrences=1,
            frequency_window_days=7,
            task_list_id=project_list.id,
            goal_id=goal.id,
        )
        session.add(routine)
        session.flush()
        task = Task(
            title="Water plants",
            task_list_id=project_list.id,
            routine_id=routine.id,
            owner_type="project",
            owner_wiki_id="prj-home",
        )
        session.add(task)
        session.commit()
        before = sorted((path.relative_to(wiki).as_posix(), path.read_bytes()) for path in wiki.rglob("*.md"))

        first = legacy_retirement_report(session, repository)
        second = legacy_retirement_report(session, repository)

        assert first == second
        assert first["mode"] == "dry-run"
        assert first["writes_performed"] is False
        assert first["summary"] == {
            "legacy_goals": 1,
            "legacy_routines": 1,
            "ready_mappings": 1,
            "blocking_exceptions": 0,
        }
        assert first["routine_mappings"] == [
            {
                "source": {"table": "routines", "row_id": routine.id, "wiki_id": None},
                "target": {"owner_type": "project", "owner_wiki_id": "prj-home"},
                "recurrence_metadata": {
                    "cadence": "weekly",
                    "next_run_date": "2026-08-24",
                    "minimum_occurrences": 1,
                    "frequency_window_days": 7,
                    "skips": [],
                },
            }
        ]
        assert first["blocking_exceptions"] == []
        assert sorted((path.relative_to(wiki).as_posix(), path.read_bytes()) for path in wiki.rglob("*.md")) == before
        assert session.get(Routine, routine.id).status == "active"


def test_legacy_retirement_report_blocks_unowned_non_inbox_routine_without_writes(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        task_list = TaskList(name="Unowned")
        session.add(task_list)
        session.flush()
        routine = Routine(
            title="Unowned recurrence",
            cadence="daily",
            next_run_date=date(2026, 8, 24),
            task_list_id=task_list.id,
        )
        session.add(routine)
        session.commit()

        report = legacy_retirement_report(session, repository)

        assert report["routine_mappings"] == []
        assert report["blocking_exceptions"] == [
            {
                "source": {"table": "routines", "row_id": routine.id, "wiki_id": None},
                "code": "routine_owner_unresolved",
                "message": "Routine has no explicit Project or Area task owner and is not in Inbox",
            }
        ]
        assert repository.list_records() == []


def test_scheduler_does_not_generate_tasks_for_retired_routines(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(tmp_path / "wiki"),
    )
    with app.state.session_factory() as session:
        inbox = TaskList(name="Inbox")
        session.add(inbox)
        session.flush()
        routine = Routine(
            title="Retired generation",
            cadence="daily",
            next_run_date=date(2026, 8, 24),
            task_list_id=inbox.id,
        )
        session.add(routine)
        session.commit()

    assert generate_due_once(app, date(2026, 8, 24)) == 0
    assert app.state.wiki_repository.list_records("task") == []


def test_new_tasks_and_projects_reject_retired_goal_or_routine_relationships(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(tmp_path / "wiki"),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    with app.state.session_factory() as session:
        inbox = TaskList(name="Inbox")
        goal = Goal(title="Legacy goal")
        session.add_all([inbox, goal])
        session.flush()
        routine = Routine(
            title="Legacy routine", cadence="daily", next_run_date=date(2026, 8, 24), task_list_id=inbox.id
        )
        session.add(routine)
        session.commit()

        goal_id, routine_id = goal.id, routine.id

    task = client.post(
        "/api/tasks",
        json={"title": "Do not link legacy goal", "task_list_id": 1, "goal_id": goal_id, "owner_type": "inbox"},
    )
    project = client.post("/api/projects", json={"title": "Do not link legacy goal", "goal_id": goal_id})
    routine_task = client.post(
        "/api/tasks",
        json={
            "title": "Do not link legacy routine",
            "task_list_id": 1,
            "routine_id": routine_id,
            "owner_type": "inbox",
        },
    )

    for response in (task, project, routine_task):
        assert response.status_code == 410
        assert response.json()["detail"]["code"] == "legacy_domain_retired"
    assert app.state.wiki_repository.list_records("task") == []
