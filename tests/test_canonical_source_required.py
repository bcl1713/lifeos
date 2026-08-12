from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from lifeos.domain import Goal, Project, Routine, Task
from lifeos.main import create_app


@pytest.mark.parametrize(
    ("path", "payload", "model"),
    [
        ("/api/goals", {"title": "No source goal"}, Goal),
        ("/api/projects", {"title": "No source project"}, Project),
    ],
)
def test_canonical_record_creation_fails_closed_without_wiki(
    tmp_path: Path, path: str, payload: dict[str, object], model
) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / (model.__tablename__ + '.db')}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204

    response = client.post(path, json=payload)

    assert response.status_code == 503
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(model)) == 0


def test_task_and_routine_creation_fail_closed_without_wiki(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'execution.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    task_list = client.post("/api/task-lists", json={"name": "Inbox"}).json()

    task_response = client.post("/api/tasks", json={"title": "No source task", "task_list_id": task_list["id"]})
    routine_response = client.post(
        "/api/routines",
        json={
            "title": "No source routine",
            "cadence": "daily",
            "task_list_id": task_list["id"],
            "start_date": "2026-08-20",
        },
    )

    assert task_response.status_code == 503
    assert routine_response.status_code == 503
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Task)) == 0
        assert session.scalar(select(func.count()).select_from(Routine)) == 0
