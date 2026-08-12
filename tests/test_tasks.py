from fastapi.testclient import TestClient

from lifeos.main import create_app


def test_authenticated_user_can_create_complete_and_reopen_task_with_audit_history(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        wiki_root=str(tmp_path / "wiki"),
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

    completed = client.post(f"/api/tasks/{task['id']}/complete", params={"expected_hash": task["wiki_hash"]})
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    reopened = client.post(
        f"/api/tasks/{task['id']}/reopen", params={"expected_hash": completed.json()["wiki_hash"]}
    )
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
        wiki_root=str(tmp_path / "wiki"),
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
        response = client.post(
            f"/api/tasks/{task['id']}/{action}", params={"expected_hash": task["wiki_hash"]}
        )
        assert response.status_code == 200
        task = response.json()
        assert task["status"] == expected

    audit = client.get(f"/api/tasks/{task['id']}/audit")
    assert [entry["action"] for entry in audit.json()] == ["created", "paused", "cancelled", "archived", "reopened"]


def test_task_api_requires_authentication_and_allows_repeated_titles(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        wiki_root=str(tmp_path / "wiki"),
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
        wiki_root=str(tmp_path / "wiki"),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    list_id = client.post("/api/task-lists", json={"name": "Personal"}).json()["id"]
    for title in ("First", "Second", "Third"):
        response = client.post("/api/tasks", json={"title": title, "task_list_id": list_id})
        assert response.status_code == 201

    second = client.get("/api/tasks").json()[1]
    client.post("/api/tasks/2/complete", params={"expected_hash": second["wiki_hash"]})
    assert len(client.get("/api/tasks", params={"status": "completed"}).json()) == 1
    assert len(client.get("/api/tasks", params={"limit": 1, "offset": 1}).json()) == 1


def test_task_dependencies_are_idempotent_and_reject_cycles(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        wiki_root=str(tmp_path / "wiki"),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    list_id = client.post("/api/task-lists", json={"name": "Personal"}).json()["id"]
    tasks = [
        client.post("/api/tasks", json={"title": title, "task_list_id": list_id}).json() for title in ("A", "B", "C")
    ]
    a, b, c = (task["id"] for task in tasks)
    by_id = {task["id"]: task for task in tasks}
    first = client.post(
        f"/api/tasks/{a}/dependencies",
        json={"depends_on_task_id": b, "expected_hash": by_id[a]["wiki_hash"]},
    )
    assert first.status_code == 201
    current_a = next(task for task in client.get("/api/tasks").json() if task["id"] == a)
    duplicate = client.post(
        f"/api/tasks/{a}/dependencies",
        json={"depends_on_task_id": b, "expected_hash": current_a["wiki_hash"]},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == first.json()["id"]
    assert client.post(
        f"/api/tasks/{b}/dependencies",
        json={"depends_on_task_id": c, "expected_hash": by_id[b]["wiki_hash"]},
    ).status_code == 201
    assert client.post(
        f"/api/tasks/{c}/dependencies",
        json={"depends_on_task_id": a, "expected_hash": by_id[c]["wiki_hash"]},
    ).status_code == 409
    assert client.post(
        f"/api/tasks/{a}/dependencies",
        json={"depends_on_task_id": a, "expected_hash": current_a["wiki_hash"]},
    ).status_code == 409
    current_tasks = {task["id"]: task for task in client.get("/api/tasks").json()}
    assert client.post(f"/api/tasks/{a}/complete", params={"expected_hash": current_tasks[a]["wiki_hash"]}).status_code == 409
    assert client.post(f"/api/tasks/{b}/complete", params={"expected_hash": current_tasks[b]["wiki_hash"]}).status_code == 409
    completed_c = client.post(f"/api/tasks/{c}/complete", params={"expected_hash": current_tasks[c]["wiki_hash"]})
    assert completed_c.status_code == 200
    completed_b = client.post(f"/api/tasks/{b}/complete", params={"expected_hash": current_tasks[b]["wiki_hash"]})
    assert completed_b.status_code == 200
    completed_a = client.post(f"/api/tasks/{a}/complete", params={"expected_hash": current_tasks[a]["wiki_hash"]})
    assert completed_a.status_code == 200
    assert client.delete(
        f"/api/tasks/{a}/dependencies/{first.json()['id']}",
        params={"expected_hash": completed_a.json()["wiki_hash"]},
    ).status_code == 204
    assert client.get(f"/api/tasks/{a}/dependencies").json() == []
    actions = [entry["action"] for entry in client.get(f"/api/tasks/{a}/audit").json()]
    assert "dependency_added" in actions
    assert "dependency_removed" in actions


def test_task_dependency_mutations_require_current_parent_hash(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'dependency-conflict.db'}",
        auth_username="brian",
        auth_password="password",
        wiki_root=str(tmp_path / "wiki"),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    list_id = client.post("/api/task-lists", json={"name": "Personal"}).json()["id"]
    parent = client.post("/api/tasks", json={"title": "Parent", "task_list_id": list_id}).json()
    prerequisite = client.post("/api/tasks", json={"title": "Prerequisite", "task_list_id": list_id}).json()

    missing = client.post(
        f"/api/tasks/{parent['id']}/dependencies",
        json={"depends_on_task_id": prerequisite["id"]},
    )
    assert missing.status_code == 409
    assert client.get(f"/api/tasks/{parent['id']}/dependencies").json() == []

    added = client.post(
        f"/api/tasks/{parent['id']}/dependencies",
        json={"depends_on_task_id": prerequisite["id"], "expected_hash": parent["wiki_hash"]},
    )
    assert added.status_code == 201
    current_parent = next(task for task in client.get("/api/tasks").json() if task["id"] == parent["id"])
    stale_delete = client.delete(
        f"/api/tasks/{parent['id']}/dependencies/{added.json()['id']}",
        params={"expected_hash": parent["wiki_hash"]},
    )
    assert stale_delete.status_code == 409
    assert len(client.get(f"/api/tasks/{parent['id']}/dependencies").json()) == 1
    assert client.delete(
        f"/api/tasks/{parent['id']}/dependencies/{added.json()['id']}",
        params={"expected_hash": current_parent["wiki_hash"]},
    ).status_code == 204


def test_task_creation_rejects_missing_related_resources(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        wiki_root=str(tmp_path / "wiki"),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    list_id = client.post("/api/task-lists", json={"name": "Personal"}).json()["id"]

    response = client.post(
        "/api/tasks",
        json={"title": "Dangling link", "task_list_id": list_id, "project_id": 999},
    )
    assert response.status_code == 404
