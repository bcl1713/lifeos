from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from lifeos.domain import Task
from lifeos.main import create_app


def test_web_ui_login_today_create_and_complete_task(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        wiki_root=str(tmp_path / "wiki"),
    )
    client = TestClient(app, follow_redirects=False)

    assert client.get("/").status_code == 303
    login_page = client.get("/login")
    assert login_page.status_code == 200
    assert "Sign in to LifeOS" in login_page.text

    login = client.post("/login", data={"username": "brian", "password": "password"})
    assert login.status_code == 303
    assert login.headers["location"] == "/"

    page = client.get("/")
    assert page.status_code == 200
    assert "Inbox" in page.text

    created = client.post("/ui/tasks", data={"title": "Review the LifeOS deployment", "task_list_id": "1"})
    assert created.status_code == 303
    assert "Review the LifeOS deployment" in client.get("/").text

    task = client.get("/api/tasks").json()[0]
    completed = client.post("/ui/tasks/1/complete", data={"expected_hash": task["wiki_hash"]})
    assert completed.status_code == 303
    assert "Review the LifeOS deployment" not in client.get("/").text
    assert "Completed" in client.get("/tasks").text

    assert client.post("/auth/logout").status_code == 204
    assert client.get("/").status_code == 303


def test_web_ui_renders_api_tag_arrays_as_individual_chips(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'tags.db'}",
        auth_username="brian",
        auth_password="password",
        wiki_root=str(tmp_path / "wiki"),
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    inbox = client.post("/api/task-lists", json={"name": "Inbox"}).json()

    created = client.post(
        "/api/tasks",
        json={
            "title": "Tag array task",
            "task_list_id": inbox["id"],
            "owner_type": "inbox",
            "tags": ["focus", "home"],
        },
    )

    assert created.status_code == 201
    assert created.json()["tags"] == ["focus", "home"]
    today = client.get("/")
    tasks = client.get("/tasks")
    for page in (today, tasks):
        assert page.status_code == 200
        assert '<li class="tag-chip">focus</li>' in page.text
        assert '<li class="tag-chip">home</li>' in page.text
        assert page.text.count('class="tag-chip"') == 2


def test_web_ui_renders_serialized_tag_strings_as_individual_chips(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'legacy-tags.db'}",
        auth_username="brian",
        auth_password="password",
        wiki_root=str(tmp_path / "wiki"),
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    inbox = client.post("/api/task-lists", json={"name": "Inbox"}).json()
    created = client.post(
        "/api/tasks",
        json={"title": "Legacy tag task", "task_list_id": inbox["id"], "owner_type": "inbox"},
    ).json()
    assert 'class="tag-chip"' not in client.get("/tasks").text
    with app.state.session_factory() as session:
        task = session.get(Task, created["id"])
        task.tags = '["legacy"]'
        session.commit()

    page = client.get("/tasks")

    assert page.status_code == 200
    assert '<li class="tag-chip">legacy</li>' in page.text
    assert page.text.count('class="tag-chip"') == 1


def test_web_task_creation_writes_source_before_projection(tmp_path, monkeypatch) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'source-first-ui.db'}",
        auth_username="brian",
        auth_password="password",
        wiki_root=str(tmp_path / "wiki"),
    )
    client = TestClient(app, follow_redirects=False)
    client.post("/login", data={"username": "brian", "password": "password"})
    client.get("/")
    repository = app.state.wiki_repository
    original_write = repository.write
    events: list[str] = []

    def observed_write(*args, **kwargs):
        events.append("source")
        return original_write(*args, **kwargs)

    def observed_flush(_session, _context):
        events.append("projection")

    monkeypatch.setattr(repository, "write", observed_write)
    event.listen(Session, "after_flush", observed_flush)
    try:
        response = client.post("/ui/tasks", data={"title": "UI source first", "task_list_id": "1"})
    finally:
        event.remove(Session, "after_flush", observed_flush)

    assert response.status_code == 303
    assert events[0] == "source"


def test_web_task_update_commit_failure_reports_reconciliation_required(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'ui-update-failure.db'}",
        auth_username="brian",
        auth_password="password",
        wiki_root=str(tmp_path / "wiki"),
    )
    client = TestClient(app, follow_redirects=False)
    client.post("/login", data={"username": "brian", "password": "password"})
    client.get("/")
    client.post("/ui/tasks", data={"title": "UI update failure", "task_list_id": "1"})
    task = client.get("/api/tasks").json()[0]

    def fail_commit(session):
        if any(item.status == "paused" for item in session.dirty if item.__class__.__name__ == "Task"):
            raise RuntimeError("simulated commit failure")

    event.listen(Session, "before_commit", fail_commit)
    try:
        response = client.post(f"/ui/tasks/{task['id']}/pause", data={"expected_hash": task["wiki_hash"]})
    finally:
        event.remove(Session, "before_commit", fail_commit)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "canonical_source_written_projection_failed"


def test_web_ui_rejects_invalid_login_and_protects_mutations(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
    )
    client = TestClient(app, follow_redirects=False)

    assert client.post("/login", data={"username": "brian", "password": "wrong"}).status_code == 401
    assert client.post("/ui/tasks", data={"title": "Should not exist", "task_list_id": "1"}).status_code == 401
