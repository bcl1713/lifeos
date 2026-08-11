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


def test_task_lifecycle_metadata_and_state_transitions_are_audited(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    list_id = client.post("/api/task-lists", json={"name": "Personal"}).json()["id"]
    created = client.post(
        "/api/tasks",
        json={
            "title": "Lifecycle task",
            "task_list_id": list_id,
            "priority": 2,
            "tags": ["focus", "home"],
            "source_ref": "wiki:02-Areas/Personal/Index.md",
        },
    )
    assert created.status_code == 201
    task = created.json()
    assert task["priority"] == 2
    assert task["tags"] == ["focus", "home"]
    assert task["source_ref"] == "wiki:02-Areas/Personal/Index.md"

    for action, expected in (("pause", "paused"), ("cancel", "cancelled"), ("archive", "archived"), ("reopen", "open")):
        response = client.post(f"/api/tasks/{task['id']}/{action}")
        assert response.status_code == 200
        assert response.json()["status"] == expected

    audit = client.get(f"/api/tasks/{task['id']}/audit")
    assert [entry["action"] for entry in audit.json()] == ["created", "paused", "cancelled", "archived", "reopened"]


def test_task_api_requires_authentication_and_allows_repeated_titles(tmp_path) -> None:
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
    assert duplicate.status_code == 201


def test_task_listing_supports_status_filter_and_pagination(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    list_id = client.post("/api/task-lists", json={"name": "Personal"}).json()["id"]
    for title in ("First", "Second", "Third"):
        response = client.post("/api/tasks", json={"title": title, "task_list_id": list_id})
        assert response.status_code == 201

    client.post("/api/tasks/2/complete")
    assert len(client.get("/api/tasks", params={"status": "completed"}).json()) == 1
    assert len(client.get("/api/tasks", params={"limit": 1, "offset": 1}).json()) == 1


def test_task_dependencies_are_idempotent_and_reject_cycles(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    list_id = client.post("/api/task-lists", json={"name": "Personal"}).json()["id"]
    tasks = [
        client.post("/api/tasks", json={"title": title, "task_list_id": list_id}).json() for title in ("A", "B", "C")
    ]
    a, b, c = (task["id"] for task in tasks)
    first = client.post(f"/api/tasks/{a}/dependencies", json={"depends_on_task_id": b})
    assert first.status_code == 201
    duplicate = client.post(f"/api/tasks/{a}/dependencies", json={"depends_on_task_id": b})
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == first.json()["id"]
    assert client.post(f"/api/tasks/{b}/dependencies", json={"depends_on_task_id": c}).status_code == 201
    assert client.post(f"/api/tasks/{c}/dependencies", json={"depends_on_task_id": a}).status_code == 409
    assert client.post(f"/api/tasks/{a}/dependencies", json={"depends_on_task_id": a}).status_code == 409
    assert client.post(f"/api/tasks/{a}/complete").status_code == 409
    assert client.post(f"/api/tasks/{b}/complete").status_code == 409
    assert client.post(f"/api/tasks/{c}/complete").status_code == 200
    assert client.post(f"/api/tasks/{b}/complete").status_code == 200
    assert client.post(f"/api/tasks/{a}/complete").status_code == 200
    assert client.delete(f"/api/tasks/{a}/dependencies/{first.json()['id']}").status_code == 204
    assert client.get(f"/api/tasks/{a}/dependencies").json() == []
    actions = [entry["action"] for entry in client.get(f"/api/tasks/{a}/audit").json()]
    assert "dependency_added" in actions
    assert "dependency_removed" in actions


def test_task_creation_rejects_missing_related_resources(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    list_id = client.post("/api/task-lists", json={"name": "Personal"}).json()["id"]

    response = client.post(
        "/api/tasks",
        json={"title": "Dangling link", "task_list_id": list_id, "project_id": 999},
    )
    assert response.status_code == 404
