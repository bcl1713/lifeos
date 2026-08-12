from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

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


def test_web_context_creation_writes_source_before_projection(tmp_path, monkeypatch) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'source-first-context-ui.db'}",
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
        events.append(f"source:{args[0]}")
        return original_write(*args, **kwargs)

    def observed_flush(_session, _context):
        events.append("projection")

    monkeypatch.setattr(repository, "write", observed_write)
    event.listen(Session, "after_flush", observed_flush)
    try:
        goal = client.post("/ui/goals", data={"title": "UI goal"})
        goal_events = list(events)
        events.clear()
        project = client.post("/ui/projects", data={"title": "UI project", "goal_id": "1"})
        project_events = list(events)
        events.clear()
        routine = client.post(
            "/ui/routines",
            data={
                "title": "UI routine",
                "cadence": "daily",
                "start_date": "2026-08-20",
                "task_list_id": "1",
                "goal_id": "1",
            },
        )
        routine_events = list(events)
    finally:
        event.remove(Session, "after_flush", observed_flush)

    assert goal.status_code == 303
    assert project.status_code == 303
    assert routine.status_code == 303
    assert goal_events[0] == "source:goal"
    assert project_events[0] == "source:project"
    assert routine_events[0] == "source:routine"


def test_web_ui_context_views_create_goal_project_and_routine(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        wiki_root=str(tmp_path / "wiki"),
    )
    client = TestClient(app, follow_redirects=False)
    client.post("/login", data={"username": "brian", "password": "password"})

    assert client.get("/goals").status_code == 200
    assert client.get("/projects").status_code == 200
    assert client.get("/routines").status_code == 200
    data = client.get("/data")
    assert data.status_code == 200
    assert "Read-only" in data.text

    goal = client.post("/ui/goals", data={"title": "Protect focus time"})
    assert goal.status_code == 303
    project = client.post("/ui/projects", data={"title": "LifeOS completion", "goal_id": "1"})
    assert project.status_code == 303
    routine = client.post(
        "/ui/routines",
        data={
            "title": "Morning review",
            "cadence": "daily",
            "start_date": "2026-08-12",
            "task_list_id": "1",
            "goal_id": "1",
        },
    )
    assert routine.status_code == 303
    assert "Protect focus time" in client.get("/goals").text
    assert "LifeOS completion" in client.get("/projects").text
    assert "Morning review" in client.get("/routines").text


def test_web_ui_rejects_invalid_login_and_protects_mutations(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
    )
    client = TestClient(app, follow_redirects=False)

    assert client.post("/login", data={"username": "brian", "password": "wrong"}).status_code == 401
    assert client.post("/ui/tasks", data={"title": "Should not exist", "task_list_id": "1"}).status_code == 401
