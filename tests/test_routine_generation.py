from fastapi.testclient import TestClient

from lifeos.main import create_app


def test_routine_generation_catches_up_and_is_idempotent(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Routines"}).json()
    routine = client.post(
        "/api/routines",
        json={
            "title": "Take bins out",
            "cadence": "daily",
            "task_list_id": task_list["id"],
            "start_date": "2026-08-11",
        },
    )
    assert routine.status_code == 201
    routine_id = routine.json()["id"]

    first = client.post(f"/api/routines/{routine_id}/generate", params={"on": "2026-08-13"})
    assert first.status_code == 200
    assert first.json()["generated"] == 3

    second = client.post(f"/api/routines/{routine_id}/generate", params={"on": "2026-08-13"})
    assert second.status_code == 200
    assert second.json()["generated"] == 0

    tasks = client.get("/api/tasks", params={"limit": 10}).json()
    assert [task["due_date"] for task in tasks] == ["2026-08-11", "2026-08-12", "2026-08-13"]
    assert all(task["routine_id"] == routine_id for task in tasks)
    assert client.get("/api/routines").json()[0]["next_run_date"] == "2026-08-14"
