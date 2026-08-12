from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from lifeos.domain import Goal, Project, Routine, Task, TaskList
from lifeos.main import create_app
from lifeos.wiki_store import WikiRepository


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
    updated = client.patch(
        f"/api/tasks/{task['id']}",
        json={"title": "Write the canonical note", "expected_hash": task["wiki_hash"]},
    )
    assert updated.status_code == 200
    assert "Write the canonical note" in path.read_text(encoding="utf-8")
    assert client.post(
        f"/api/tasks/{task['id']}/complete", params={"expected_hash": updated.json()["wiki_hash"]}
    ).status_code == 200
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
    missing = client.patch(f"/api/tasks/{task['id']}", json={"title": "No hash"})
    assert missing.status_code == 409
    assert client.get("/api/tasks").json()[0]["title"] == "Protect external edit"
    path = wiki / task["wiki_path"]
    path.write_text(path.read_text(encoding="utf-8") + "\nExternal edit.\n", encoding="utf-8")
    response = client.patch(
        f"/api/tasks/{task['id']}",
        json={"title": "Overwrite attempt", "expected_hash": task["wiki_hash"]},
    )
    assert response.status_code == 409
    assert "External edit." in path.read_text(encoding="utf-8")


def test_task_update_rejects_canonical_identity_path_disagreement(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'task-identity-path.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Inbox"}).json()
    first = client.post("/api/tasks", json={"title": "First identity", "task_list_id": task_list["id"]}).json()
    second = client.post("/api/tasks", json={"title": "Second path", "task_list_id": task_list["id"]}).json()
    with app.state.session_factory() as session:
        projected = session.get(Task, first["id"])
        projected.wiki_path = second["wiki_path"]
        projected.wiki_hash = second["wiki_hash"]
        session.commit()
    before = {item["wiki_path"]: (wiki / item["wiki_path"]).read_bytes() for item in (first, second)}

    response = client.patch(
        f"/api/tasks/{first['id']}",
        json={"status": "paused", "expected_hash": second["wiki_hash"]},
    )

    assert response.status_code == 409
    assert "identity and path disagree" in response.text
    assert {path: (wiki / path).read_bytes() for path in before} == before


def test_task_update_rejects_missing_identity_with_occupied_canonical_path(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'task-missing-identity.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Inbox"}).json()
    canonical = client.post(
        "/api/tasks", json={"title": "Canonical owner", "task_list_id": task_list["id"]}
    ).json()
    with app.state.session_factory() as session:
        projected = session.get(Task, canonical["id"])
        projected.wiki_id = "tsk-nonexistent"
        session.commit()
    path = wiki / canonical["wiki_path"]
    before = path.read_bytes()

    response = client.patch(
        f"/api/tasks/{canonical['id']}",
        json={"status": "paused", "expected_hash": canonical["wiki_hash"]},
    )

    assert response.status_code == 409
    assert "disappeared" in response.text
    assert path.read_bytes() == before
    assert app.state.wiki_repository.read(canonical["wiki_path"]).record_id == canonical["wiki_id"]


def test_task_update_rejects_missing_explicit_canonical_path(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'task-missing-path.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Inbox"}).json()
    task = client.post("/api/tasks", json={"title": "Missing source", "task_list_id": task_list["id"]}).json()
    source = wiki / task["wiki_path"]
    source.unlink()

    response = client.patch(
        f"/api/tasks/{task['id']}",
        json={"status": "paused", "expected_hash": task["wiki_hash"]},
    )

    assert response.status_code == 409
    assert "path disappeared" in response.text
    assert not source.exists()


def test_task_status_requires_current_wiki_hash(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'status.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    task_list = client.post("/api/task-lists", json={"name": "Inbox"}).json()
    task = client.post("/api/tasks", json={"title": "Guard status", "task_list_id": task_list["id"]}).json()

    assert client.post(f"/api/tasks/{task['id']}/complete").status_code == 409
    path = wiki / task["wiki_path"]
    path.write_text(path.read_text(encoding="utf-8") + "\nExternal edit.\n", encoding="utf-8")
    stale = client.post(
        f"/api/tasks/{task['id']}/complete",
        params={"expected_hash": task["wiki_hash"]},
    )
    assert stale.status_code == 409
    assert client.get("/api/tasks").json()[0]["status"] == "open"

    current = app.state.wiki_repository.read(task["wiki_path"])
    completed = client.post(
        f"/api/tasks/{task['id']}/complete",
        params={"expected_hash": current.content_hash},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["wiki_hash"] != current.content_hash


def test_task_creation_writes_canonical_source_before_projection(tmp_path: Path, monkeypatch) -> None:
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
        response = client.post(
            "/api/tasks",
            json={"title": "Source first", "task_list_id": task_list["id"]},
        )
    finally:
        event.remove(Session, "after_flush", observed_flush)

    assert response.status_code == 201
    assert events.index("source") < events.index("projection")
    assert (wiki / response.json()["wiki_path"]).is_file()


def test_goal_creation_writes_canonical_source_before_projection(tmp_path: Path, monkeypatch) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'goals.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
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
        response = client.post("/api/goals", json={"title": "Source-first goal"})
    finally:
        event.remove(Session, "after_flush", observed_flush)

    assert response.status_code == 201
    assert events.index("source") < events.index("projection")
    assert (wiki / response.json()["wiki_path"]).is_file()


def test_context_updates_require_current_wiki_hash(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'context-conflicts.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    task_list = client.post("/api/task-lists", json={"name": "Routines"}).json()
    goal = client.post("/api/goals", json={"title": "Guarded goal"}).json()
    project = client.post("/api/projects", json={"title": "Guarded project", "goal_id": goal["id"]}).json()
    routine = client.post(
        "/api/routines",
        json={
            "title": "Guarded routine",
            "cadence": "daily",
            "task_list_id": task_list["id"],
            "goal_id": goal["id"],
            "start_date": "2026-08-20",
        },
    ).json()

    for kind, resource in (("goals", goal), ("projects", project), ("routines", routine)):
        assert client.patch(f"/api/{kind}/{resource['id']}", json={"status": "paused"}).status_code == 409
        updated = client.patch(
            f"/api/{kind}/{resource['id']}",
            json={"status": "paused", "expected_hash": resource["wiki_hash"]},
        )
        assert updated.status_code == 200
        assert updated.json()["status"] == "paused"
        assert updated.json()["wiki_hash"] != resource["wiki_hash"]


def test_project_and_routine_relationship_updates_write_stable_canonical_fields(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'relationships.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    first_goal = client.post("/api/goals", json={"title": "First goal"}).json()
    second_goal = client.post("/api/goals", json={"title": "Second goal"}).json()
    first_list = client.post("/api/task-lists", json={"name": "First list"}).json()
    second_list = client.post("/api/task-lists", json={"name": "Second list"}).json()
    project = client.post("/api/projects", json={"title": "Move project", "goal_id": first_goal["id"]}).json()
    routine = client.post(
        "/api/routines",
        json={
            "title": "Move routine",
            "cadence": "daily",
            "task_list_id": first_list["id"],
            "goal_id": first_goal["id"],
            "start_date": "2026-08-20",
        },
    ).json()

    project_update = client.patch(
        f"/api/projects/{project['id']}",
        json={"goal_id": second_goal["id"], "expected_hash": project["wiki_hash"]},
    )
    routine_update = client.patch(
        f"/api/routines/{routine['id']}",
        json={
            "goal_id": second_goal["id"],
            "task_list_id": second_list["id"],
            "expected_hash": routine["wiki_hash"],
        },
    )

    assert project_update.status_code == 200
    assert routine_update.status_code == 200
    project_record = app.state.wiki_repository.find_by_id(project["wiki_id"])
    routine_record = app.state.wiki_repository.find_by_id(routine["wiki_id"])
    assert project_record.fields["goal_wiki_id"] == second_goal["wiki_id"]
    assert "goal_id" not in project_record.fields
    assert routine_record.fields["goal_wiki_id"] == second_goal["wiki_id"]
    assert routine_record.fields["task_list"] == "Second list"
    assert "goal_id" not in routine_record.fields
    assert "task_list_id" not in routine_record.fields


def test_project_update_never_adopts_same_title_canonical_identity(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'project-title-takeover.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    canonical = client.post("/api/projects", json={"title": "Repeated project"}).json()
    with app.state.session_factory() as session:
        legacy = Project(title="Repeated project", status="active")
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id

    before = (wiki / canonical["wiki_path"]).read_bytes()
    response = client.patch(
        f"/api/projects/{legacy_id}",
        json={"status": "paused", "expected_hash": canonical["wiki_hash"]},
    )

    assert response.status_code == 409
    assert (wiki / canonical["wiki_path"]).read_bytes() == before
    with app.state.session_factory() as session:
        projected = session.get(Project, legacy_id)
        assert projected.wiki_id is None
        assert projected.status == "active"


def test_project_and_routine_creation_write_source_before_projection(tmp_path: Path, monkeypatch) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'context.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    task_list = client.post("/api/task-lists", json={"name": "Routines"}).json()
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
        project = client.post("/api/projects", json={"title": "Source-first project"})
        project_events = list(events)
        events.clear()
        routine = client.post(
            "/api/routines",
            json={
                "title": "Source-first routine",
                "cadence": "daily",
                "task_list_id": task_list["id"],
                "start_date": "2026-08-20",
            },
        )
        routine_events = list(events)
    finally:
        event.remove(Session, "after_flush", observed_flush)

    assert project.status_code == 201
    assert routine.status_code == 201
    assert project_events[0] == "source:project"
    assert routine_events[0] == "source:routine"


def test_milestone_and_skip_write_parent_source_before_child_projection(tmp_path: Path, monkeypatch) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'nested-source-first.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(tmp_path / "wiki"),
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    task_list = client.post("/api/task-lists", json={"name": "Routines"}).json()
    goal = client.post("/api/goals", json={"title": "Ordered goal"}).json()
    routine = client.post(
        "/api/routines",
        json={
            "title": "Ordered routine",
            "cadence": "daily",
            "task_list_id": task_list["id"],
            "start_date": "2026-08-20",
        },
    ).json()
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
        milestone = client.post(
            f"/api/goals/{goal['id']}/milestones",
            json={"title": "Ordered milestone", "expected_hash": goal["wiki_hash"]},
        )
        milestone_events = list(events)
        events.clear()
        skip = client.post(
            f"/api/routines/{routine['id']}/skip",
            json={
                "scheduled_date": "2026-08-20",
                "reason": "Ordered skip",
                "expected_hash": routine["wiki_hash"],
            },
        )
        skip_events = list(events)
    finally:
        event.remove(Session, "after_flush", observed_flush)

    assert milestone.status_code == 201
    assert skip.status_code == 201
    assert milestone_events[0] == "source:goal"
    assert skip_events[0] == "source:routine"


def test_domain_updates_write_source_before_projection_flush(tmp_path: Path, monkeypatch) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'update-order.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(tmp_path / "wiki"),
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    task_list = client.post("/api/task-lists", json={"name": "Inbox"}).json()
    task = client.post("/api/tasks", json={"title": "Ordered task", "task_list_id": task_list["id"]}).json()
    goal = client.post("/api/goals", json={"title": "Ordered goal update"}).json()
    project = client.post("/api/projects", json={"title": "Ordered project update"}).json()
    routine = client.post(
        "/api/routines",
        json={
            "title": "Ordered routine update",
            "cadence": "daily",
            "task_list_id": task_list["id"],
            "start_date": "2026-08-20",
        },
    ).json()
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
        requests = (
            ("task", f"/api/tasks/{task['id']}", {"title": "Updated task", "expected_hash": task["wiki_hash"]}),
            ("goal", f"/api/goals/{goal['id']}", {"status": "paused", "expected_hash": goal["wiki_hash"]}),
            (
                "project",
                f"/api/projects/{project['id']}",
                {"status": "paused", "expected_hash": project["wiki_hash"]},
            ),
            (
                "routine",
                f"/api/routines/{routine['id']}",
                {"status": "paused", "expected_hash": routine["wiki_hash"]},
            ),
        )
        for record_type, path, payload in requests:
            events.clear()
            response = client.patch(path, json=payload)
            assert response.status_code == 200
            assert events[0] == f"source:{record_type}"
    finally:
        event.remove(Session, "after_flush", observed_flush)


def test_task_status_and_dependency_writes_are_source_first(tmp_path: Path, monkeypatch) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'task-mutation-order.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(tmp_path / "wiki"),
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    task_list = client.post("/api/task-lists", json={"name": "Inbox"}).json()
    parent = client.post("/api/tasks", json={"title": "Ordered parent", "task_list_id": task_list["id"]}).json()
    prerequisite = client.post(
        "/api/tasks", json={"title": "Ordered prerequisite", "task_list_id": task_list["id"]}
    ).json()
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
        status_response = client.post(
            f"/api/tasks/{prerequisite['id']}/complete",
            params={"expected_hash": prerequisite["wiki_hash"]},
        )
        status_events = list(events)
        events.clear()
        added = client.post(
            f"/api/tasks/{parent['id']}/dependencies",
            json={"depends_on_task_id": prerequisite["id"], "expected_hash": parent["wiki_hash"]},
        )
        add_events = list(events)
        current_parent = next(task for task in client.get("/api/tasks").json() if task["id"] == parent["id"])
        events.clear()
        removed = client.delete(
            f"/api/tasks/{parent['id']}/dependencies/{added.json()['id']}",
            params={"expected_hash": current_parent["wiki_hash"]},
        )
        remove_events = list(events)
    finally:
        event.remove(Session, "after_flush", observed_flush)

    assert status_response.status_code == 200
    assert added.status_code == 201
    assert removed.status_code == 204
    assert status_events[0] == "source:task"
    assert add_events[0] == "source:task"
    assert remove_events[0] == "source:task"


@pytest.mark.parametrize(
    ("endpoint", "payload", "model", "record_type"),
    [
        ("/api/goals", {"title": "Projection failure goal"}, Goal, "goal"),
        ("/api/projects", {"title": "Projection failure project"}, Project, "project"),
    ],
)
def test_context_create_reports_reconciliation_required_after_source_write(
    tmp_path: Path, endpoint: str, payload: dict, model, record_type: str
) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / f'{record_type}.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})

    def fail_projection(session, _context, _instances):
        if any(isinstance(item, model) and item.title.startswith("Projection failure") for item in session.new):
            raise RuntimeError("simulated projection failure")

    event.listen(Session, "before_flush", fail_projection)
    try:
        response = client.post(endpoint, json=payload)
    finally:
        event.remove(Session, "before_flush", fail_projection)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "canonical_source_written_projection_failed"
    assert detail["wiki_id"].startswith(f"{record_type if record_type == 'goal' else 'prj'}-")
    assert (wiki / detail["wiki_path"]).is_file()
    with app.state.session_factory() as session:
        assert session.query(model).count() == 0


def test_task_and_routine_create_report_reconciliation_required_after_source_write(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'task-routine.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Inbox"}).json()

    def fail_projection(session, _context, _instances):
        if any(
            isinstance(item, (Task, Routine)) and item.title.startswith("Projection failure")
            for item in session.new
        ):
            raise RuntimeError("simulated projection failure")

    event.listen(Session, "before_flush", fail_projection)
    try:
        task_response = client.post(
            "/api/tasks",
            json={"title": "Projection failure task", "task_list_id": task_list["id"]},
        )
        routine_response = client.post(
            "/api/routines",
            json={
                "title": "Projection failure routine",
                "cadence": "daily",
                "task_list_id": task_list["id"],
                "start_date": "2026-08-20",
            },
        )
    finally:
        event.remove(Session, "before_flush", fail_projection)

    for response in (task_response, routine_response):
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["code"] == "canonical_source_written_projection_failed"
        assert (wiki / detail["wiki_path"]).is_file()
    with app.state.session_factory() as session:
        assert session.query(Task).count() == 0
        assert session.query(Routine).count() == 0


def test_task_update_commit_failure_reports_reconciliation_required(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'update-failure.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Inbox"}).json()
    task = client.post("/api/tasks", json={"title": "Update failure", "task_list_id": task_list["id"]}).json()

    def fail_commit(session):
        if any(item.status == "paused" for item in session.dirty if isinstance(item, Task)):
            raise RuntimeError("simulated commit failure")

    event.listen(Session, "before_commit", fail_commit)
    try:
        response = client.post(f"/api/tasks/{task['id']}/pause", params={"expected_hash": task["wiki_hash"]})
    finally:
        event.remove(Session, "before_commit", fail_commit)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "canonical_source_written_projection_failed"
    assert detail["wiki_id"] == task["wiki_id"]
    assert detail["wiki_path"] == task["wiki_path"]
    assert WikiRepository(wiki).find_by_id(task["wiki_id"]).fields["status"] == "paused"
    with app.state.session_factory() as session:
        assert session.get(Task, task["id"]).status == "open"


def test_legacy_task_update_failure_reports_new_canonical_identity(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'legacy-update-failure.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    client.post("/api/task-lists", json={"name": "Inbox"})
    source = WikiRepository(wiki).write(
        "task",
        "Legacy projection task",
        {"id": "tsk-legacy-projection-task", "status": "open", "task_list": "Inbox"},
    )
    with app.state.session_factory() as session:
        task_list = session.query(TaskList).first()
        legacy = Task(
            title="Legacy projection task",
            task_list_id=task_list.id,
            status="open",
            wiki_path=source.path,
            wiki_hash=source.content_hash,
        )
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id

    def fail_commit(session):
        if any(item.id == legacy_id and item.status == "paused" for item in session.dirty if isinstance(item, Task)):
            raise RuntimeError("simulated commit failure")

    event.listen(Session, "before_commit", fail_commit)
    try:
        response = client.post(f"/api/tasks/{legacy_id}/pause", params={"expected_hash": source.content_hash})
    finally:
        event.remove(Session, "before_commit", fail_commit)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["wiki_id"] == "tsk-legacy-projection-task"
    assert detail["wiki_path"]
    assert (wiki / detail["wiki_path"]).is_file()
    with app.state.session_factory() as session:
        projected = session.get(Task, legacy_id)
        assert projected.wiki_id is None
        assert projected.status == "open"


def test_task_update_source_permission_failure_is_not_misreported_as_projection_failure(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'source-permission.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Inbox"}).json()
    task = client.post("/api/tasks", json={"title": "Unreadable source", "task_list_id": task_list["id"]}).json()
    source = wiki / task["wiki_path"]
    source.chmod(0)
    try:
        response = client.patch(
            f"/api/tasks/{task['id']}",
            json={"notes": "must not claim source write", "expected_hash": task["wiki_hash"]},
        )
    finally:
        source.chmod(0o600)

    assert response.status_code == 500
    assert "canonical_source_written_projection_failed" not in response.text
