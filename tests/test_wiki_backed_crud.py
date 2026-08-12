from pathlib import Path

from fastapi.testclient import TestClient

from lifeos.main import create_app


def test_api_task_create_update_and_completion_write_canonical_wiki(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    task_list = client.post("/api/task-lists", json={"name": "Inbox"}).json()
    created = client.post("/api/tasks", json={"title": "Write canonical note", "task_list_id": task_list["id"], "notes": "Keep prose"})
    assert created.status_code == 201
    task = created.json()
    path = wiki / task["wiki_path"]
    assert path.exists()
    assert "Write canonical note" in path.read_text(encoding="utf-8")
    updated = client.patch(f"/api/tasks/{task['id']}", json={"title": "Write the canonical note"})
    assert updated.status_code == 200
    assert "Write the canonical note" in path.read_text(encoding="utf-8")
    assert client.post(f"/api/tasks/{task['id']}/complete").status_code == 200
    assert "status: completed" in path.read_text(encoding="utf-8")


def test_api_task_update_rejects_stale_wiki_hash(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    task_list = client.post("/api/task-lists", json={"name": "Inbox"}).json()
    task = client.post("/api/tasks", json={"title": "Protect external edit", "task_list_id": task_list["id"]}).json()
    path = wiki / task["wiki_path"]
    path.write_text(path.read_text(encoding="utf-8") + "\nExternal edit.\n", encoding="utf-8")
    response = client.patch(
        f"/api/tasks/{task['id']}",
        json={"title": "Overwrite attempt", "expected_hash": task["wiki_hash"]},
    )
    assert response.status_code == 409
    assert "External edit." in path.read_text(encoding="utf-8")
