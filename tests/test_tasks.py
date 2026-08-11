
from fastapi.testclient import TestClient

from lifeos.main import create_app


def test_authenticated_user_can_create_complete_and_reopen_task_with_audit_history(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})

    task_list = client.post("/api/task-lists", json={"name": "Personal"})
    assert task_list.status_code == 201
    list_id = task_list.json()["id"]

    created = client.post(
        "/api/tasks",
        json={
            "title": "Review today",
            "task_list_id": list_id,
            "due_date": "2026-08-12",
            "notes": "Keep it short",
        },
    )
    assert created.status_code == 201
    task = created.json()
    assert task["status"] == "open"
    assert task["due_date"] == "2026-08-12"

    completed = client.post(f"/api/tasks/{task['id']}/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    reopened = client.post(f"/api/tasks/{task['id']}/reopen")
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "open"

    audit = client.get(f"/api/tasks/{task['id']}/audit")
    assert audit.status_code == 200
    assert [entry["action"] for entry in audit.json()] == [
        "created",
        "completed",
        "reopened",
    ]


def test_task_api_requires_authentication_and_rejects_duplicate_titles(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        agent_token="agent-secret",
    )
    client = TestClient(app)

    assert client.get("/api/task-lists").status_code == 401
    headers = {"Authorization": "Bearer agent-secret"}
    first = client.post("/api/task-lists", headers=headers, json={"name": "Personal"})
    assert first.status_code == 201
    list_id = first.json()["id"]

    payload = {"title": "Same task", "task_list_id": list_id}
    assert client.post("/api/tasks", headers=headers, json=payload).status_code == 201
    duplicate = client.post("/api/tasks", headers=headers, json=payload)
    assert duplicate.status_code == 409
