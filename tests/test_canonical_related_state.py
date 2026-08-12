from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lifeos.domain import Goal, GoalMilestone, Routine, RoutineSkip, Task, TaskDependency
from lifeos.main import create_app
from lifeos.scripts_bridge import sync_wiki_projection
from lifeos.wiki_store import WikiRepository


def _login(client: TestClient) -> None:
    response = client.post("/auth/login", json={"username": "brian", "password": "password"})
    assert response.status_code == 204


def test_task_dependencies_round_trip_through_canonical_wiki_ids(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source_app = create_app(
        database_url=f"sqlite:///{tmp_path / 'source.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(source_app)
    _login(client)
    task_list = client.post("/api/task-lists", json={"name": "Personal"}).json()
    dependent = client.post("/api/tasks", json={"title": "Dependent", "task_list_id": task_list["id"]}).json()
    prerequisite = client.post("/api/tasks", json={"title": "Prerequisite", "task_list_id": task_list["id"]}).json()

    response = client.post(
        f"/api/tasks/{dependent['id']}/dependencies",
        json={"depends_on_task_id": prerequisite["id"], "expected_hash": dependent["wiki_hash"]},
    )
    assert response.status_code == 201

    dependent_record = WikiRepository(wiki).find_by_id(dependent["wiki_id"])
    assert dependent_record is not None
    assert dependent_record.fields["depends_on"] == [prerequisite["wiki_id"]]

    rebuilt_app = create_app(
        database_url=f"sqlite:///{tmp_path / 'rebuilt.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    with rebuilt_app.state.session_factory() as session:
        sync_wiki_projection(session, WikiRepository(wiki))
        rebuilt_dependent = session.scalar(select(Task).where(Task.wiki_id == dependent["wiki_id"]))
        rebuilt_prerequisite = session.scalar(select(Task).where(Task.wiki_id == prerequisite["wiki_id"]))
        assert rebuilt_dependent is not None
        assert rebuilt_prerequisite is not None
        edge = session.scalar(
            select(TaskDependency).where(
                TaskDependency.task_id == rebuilt_dependent.id,
                TaskDependency.depends_on_task_id == rebuilt_prerequisite.id,
            )
        )
        assert edge is not None


def test_goal_milestones_round_trip_through_canonical_markdown(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source_app = create_app(
        database_url=f"sqlite:///{tmp_path / 'source-goals.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(source_app)
    _login(client)
    goal = client.post("/api/goals", json={"title": "Ship LifeOS"}).json()
    milestone = client.post(
        f"/api/goals/{goal['id']}/milestones",
        json={"title": "Prove rebuild", "due_date": "2026-08-20", "expected_hash": goal["wiki_hash"]},
    ).json()
    created_goal_record = WikiRepository(wiki).find_by_id(goal["wiki_id"])
    assert created_goal_record is not None
    assert created_goal_record.fields["milestones"][0]["title"] == "Prove rebuild"
    assert created_goal_record.fields["milestones"][0]["status"] == "open"
    current_goal = client.get("/api/goals").json()[0]
    response = client.patch(
        f"/api/goals/{goal['id']}/milestones/{milestone['id']}",
        json={"status": "completed", "expected_hash": current_goal["wiki_hash"]},
    )
    assert response.status_code == 200

    goal_record = WikiRepository(wiki).find_by_id(goal["wiki_id"])
    assert goal_record is not None
    assert goal_record.fields["milestones"][0]["id"] == "mil-prove-rebuild"
    assert goal_record.fields["milestones"][0]["status"] == "completed"
    assert goal_record.fields["milestones"][0]["due_date"] == "2026-08-20"

    rebuilt_app = create_app(
        database_url=f"sqlite:///{tmp_path / 'rebuilt-goals.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    with rebuilt_app.state.session_factory() as session:
        sync_wiki_projection(session, WikiRepository(wiki))
        rebuilt_goal = session.scalar(select(Goal).where(Goal.wiki_id == goal["wiki_id"]))
        assert rebuilt_goal is not None
        rebuilt_milestone = session.scalar(
            select(GoalMilestone).where(GoalMilestone.goal_id == rebuilt_goal.id)
        )
        assert rebuilt_milestone is not None
        assert rebuilt_milestone.title == "Prove rebuild"
        assert rebuilt_milestone.status == "completed"
        assert rebuilt_milestone.due_date.isoformat() == "2026-08-20"


def test_routine_skips_round_trip_through_canonical_markdown(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source_app = create_app(
        database_url=f"sqlite:///{tmp_path / 'source-routines.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(source_app)
    _login(client)
    task_list = client.post("/api/task-lists", json={"name": "Routines"}).json()
    routine = client.post(
        "/api/routines",
        json={
            "title": "Stretch",
            "cadence": "daily",
            "task_list_id": task_list["id"],
            "start_date": "2026-08-20",
        },
    ).json()
    response = client.post(
        f"/api/routines/{routine['id']}/skip",
        json={"scheduled_date": "2026-08-20", "reason": "Travel", "expected_hash": routine["wiki_hash"]},
    )
    assert response.status_code == 201

    routine_record = WikiRepository(wiki).find_by_id(routine["wiki_id"])
    assert routine_record is not None
    assert routine_record.fields["skips"] == [{"scheduled_date": "2026-08-20", "reason": "Travel"}]

    rebuilt_app = create_app(
        database_url=f"sqlite:///{tmp_path / 'rebuilt-routines.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    with rebuilt_app.state.session_factory() as session:
        sync_wiki_projection(session, WikiRepository(wiki))
        rebuilt_routine = session.scalar(select(Routine).where(Routine.wiki_id == routine["wiki_id"]))
        assert rebuilt_routine is not None
        rebuilt_skip = session.scalar(select(RoutineSkip).where(RoutineSkip.routine_id == rebuilt_routine.id))
        assert rebuilt_skip is not None
        assert rebuilt_skip.scheduled_date.isoformat() == "2026-08-20"
        assert rebuilt_skip.reason == "Travel"
