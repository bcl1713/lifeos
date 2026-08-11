from fastapi.testclient import TestClient

from lifeos.main import create_app


def test_goal_project_routine_resources_link_to_tasks(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})

    goal = client.post("/api/goals", json={"title": "Keep the household running"})
    assert goal.status_code == 201
    goal_id = goal.json()["id"]

    project = client.post(
        "/api/projects",
        json={"title": "LifeOS implementation", "goal_id": goal_id},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

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


def test_context_resources_require_authentication(tmp_path) -> None:
    app = create_app(database_url=f"sqlite:///{tmp_path / 'lifeos.db'}")
    client = TestClient(app)

    for path in ("/api/goals", "/api/projects", "/api/routines"):
        assert client.get(path).status_code == 401
