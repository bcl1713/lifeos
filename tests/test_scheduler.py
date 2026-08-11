from datetime import date

from fastapi.testclient import TestClient

from lifeos.main import create_app
from lifeos.scheduler import generate_due_once


def test_scheduler_once_generates_due_routine_tasks(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Routines"}).json()
    routine = client.post(
        "/api/routines",
        json={
            "title": "Morning review",
            "cadence": "daily",
            "task_list_id": task_list["id"],
            "start_date": "2026-08-13",
        },
    ).json()

    assert generate_due_once(app, date(2026, 8, 13)) == 1
    assert client.get("/api/tasks").json()[0]["routine_id"] == routine["id"]


def test_scheduler_lifespan_starts_and_stops_cleanly(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        scheduler_enabled=True,
        scheduler_interval_seconds=1,
    )
    with TestClient(app):
        assert app.state.scheduler_task is not None
        assert not app.state.scheduler_task.done()
    assert app.state.scheduler_task.done()
