from pathlib import Path

from fastapi.testclient import TestClient

from lifeos.main import create_app


def _app(tmp_path: Path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    return create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        wiki_root=str(wiki),
        scheduler_enabled=False,
    )


def test_web_ui_login_protects_checkbox_read_surfaces(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path), follow_redirects=False)

    assert client.get("/").status_code == 303
    login_page = client.get("/login")
    assert login_page.status_code == 200
    assert "Sign in to LifeOS" in login_page.text

    login = client.post("/login", data={"username": "brian", "password": "password"})
    assert login.status_code == 303
    assert login.headers["location"] == "/"
    assert "No open checkbox observations" in client.get("/").text

    assert client.post("/auth/logout").status_code == 204
    assert client.get("/tasks").status_code == 401


def test_web_ui_fences_legacy_sql_task_rows_from_checkbox_read_surfaces(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    task_list = client.post("/api/task-lists", json={"name": "Inbox"}).json()
    created = client.post(
        "/api/tasks",
        json={"title": "Legacy SQL task", "task_list_id": task_list["id"], "owner_type": "inbox"},
    )

    assert created.status_code == 201
    page = client.get("/tasks")
    assert page.status_code == 200
    assert "Legacy SQL task" not in page.text
    assert "/ui/tasks/" not in page.text
    assert "Checkbox state is read-only in LifeOS" in page.text
