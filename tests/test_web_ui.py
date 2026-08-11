from fastapi.testclient import TestClient

from lifeos.main import create_app


def test_web_ui_login_today_create_and_complete_task(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
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

    completed = client.post("/ui/tasks/1/complete")
    assert completed.status_code == 303
    assert "Review the LifeOS deployment" not in client.get("/").text
    assert "Completed" in client.get("/tasks").text

    assert client.post("/auth/logout").status_code == 204
    assert client.get("/").status_code == 303


def test_web_ui_context_views_create_goal_project_and_routine(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
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
