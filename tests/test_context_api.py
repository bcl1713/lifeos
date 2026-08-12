from fastapi.testclient import TestClient

from lifeos.domain import AuditRecord
from lifeos.main import create_app


def test_goal_project_routine_resources_link_to_tasks(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})

    goal = client.post(
        "/api/goals",
        json={
            "title": "Keep the household running",
            "outcome": "A reliable weekly household operating rhythm",
            "baseline": "Ad hoc and inconsistent",
            "target": "Weekly review completed by Sunday evening",
            "rationale": "Reduce dropped follow-ups",
            "constraints": "Limited evening time",
            "review_cadence": "weekly",
            "review_date": "2026-08-16",
            "adjustment_trigger": "Two missed reviews in a row",
        },
    )
    assert goal.status_code == 201
    assert goal.json()["target"] == "Weekly review completed by Sunday evening"
    assert goal.json()["review_date"] == "2026-08-16"
    goal_id = goal.json()["id"]

    project = client.post(
        "/api/projects",
        json={
            "title": "LifeOS implementation",
            "owner": "Brian",
            "collaborators": "Hester",
            "scope": "Canonical task and context workflows",
            "non_goals": "Public multi-tenant service",
            "risks": "Migration drift",
            "deadline": "2026-12-31",
            "review_trigger": "Phase acceptance audit",
            "source_refs": "lifeos-project-note",
            "goal_id": goal_id,
        },
    )
    assert project.status_code == 201
    assert project.json()["scope"] == "Canonical task and context workflows"
    assert project.json()["deadline"] == "2026-12-31"
    project_id = project.json()["id"]

    resource = client.post(
        "/api/resources",
        json={
            "title": "LifeOS design reference",
            "canonical_url": "https://example.com/lifeos",
            "resource_type": "documentation",
            "description": "Reference material",
            "accessed_at": "2026-08-12",
            "source_refs": "source-1",
        },
    )
    assert resource.status_code == 201
    assert resource.json()["canonical_url"] == "https://example.com/lifeos"
    idea = client.post(
        "/api/ideas",
        json={
            "title": "Promote resource-backed workflow",
            "rationale": "Reduce context loss",
            "experiment": "Try a weekly review",
            "next_action": "Draft checklist",
            "source_refs": "source-1",
            "project_id": project_id,
        },
    )
    assert idea.status_code == 201
    assert idea.json()["project_id"] == project_id
    idea_id = idea.json()["id"]
    promoted = client.patch(f"/api/ideas/{idea_id}", json={"status": "promoted"})
    assert promoted.status_code == 200
    assert promoted.json()["status"] == "promoted"
    assert client.post("/api/ideas", json={"title": "Bad link", "project_id": 9999}).status_code == 404

    task_list = client.post("/api/task-lists", json={"name": "Personal"}).json()
    routine = client.post(
        "/api/routines",
        json={
            "title": "Weekly planning",
            "cadence": "weekly",
            "goal_id": goal_id,
            "task_list_id": 1,
            "start_date": "2026-08-11",
        },
    )
    assert routine.status_code == 201
    routine_id = routine.json()["id"]

    task = client.post(
        "/api/tasks",
        json={
            "title": "Review implementation",
            "task_list_id": task_list["id"],
            "goal_id": goal_id,
            "project_id": project_id,
            "routine_id": routine_id,
        },
    )
    assert task.status_code == 201
    assert task.json()["goal_id"] == goal_id
    assert task.json()["project_id"] == project_id
    assert task.json()["routine_id"] == routine_id

    assert client.patch(f"/api/projects/{project_id}", json={"status": "completed"}).json()["status"] == "completed"
    assert client.get("/api/goals").json()[0]["title"] == "Keep the household running"
    assert client.get("/api/projects").json()[0]["goal_id"] == goal_id
    assert client.get("/api/routines").json()[0]["cadence"] == "weekly"
    with app.state.session_factory() as session:
        assert (
            session.query(AuditRecord).filter(AuditRecord.entity_type.in_(["goal", "project", "routine"])).count() >= 4
        )
    assert client.patch(f"/api/goals/{goal_id}", json={"status": "made-up"}).status_code == 422
    milestone = client.post(f"/api/goals/{goal_id}/milestones", json={"title": "Ship the first release"})
    assert milestone.status_code == 201
    assert client.get("/api/goals").json()[0]["progress"] == 0.0
    milestone_id = milestone.json()["id"]
    assert (
        client.patch(f"/api/goals/{goal_id}/milestones/{milestone_id}", json={"status": "completed"}).status_code == 200
    )
    goal_view = client.get("/api/goals").json()[0]
    assert goal_view["milestones_completed"] == 1
    assert goal_view["progress"] == 100.0


def test_context_resources_require_authentication(tmp_path) -> None:
    app = create_app(database_url=f"sqlite:///{tmp_path / 'lifeos.db'}")
    client = TestClient(app)

    for path in ("/api/goals", "/api/projects", "/api/routines"):
        assert client.get(path).status_code == 401
