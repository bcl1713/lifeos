from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import Task
from lifeos.main import create_app
from lifeos.scripts_bridge import reconcile_wiki_projection, sync_wiki_projection
from lifeos.wiki_store import WikiRepository


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
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
    return client, wiki


def test_new_non_inbox_tasks_require_a_canonical_owner_and_use_owner_paths(tmp_path: Path) -> None:
    client, wiki = _client(tmp_path)
    task_list = client.post("/api/task-lists", json={"name": "Personal"}).json()
    project = client.post("/api/projects", json={"title": "Renovate kitchen"}).json()
    area = client.post("/api/areas", json={"title": "House"}).json()

    rejected = client.post("/api/tasks", json={"title": "Unowned", "task_list_id": task_list["id"]})
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "non-Inbox tasks require an explicit Project or Area owner"

    project_task = client.post(
        "/api/tasks",
        json={
            "title": "Book contractor",
            "task_list_id": task_list["id"],
            "owner_type": "project",
            "owner_wiki_id": project["wiki_id"],
        },
    )
    assert project_task.status_code == 201
    assert project_task.json()["owner_type"] == "project"
    assert project_task.json()["owner_wiki_id"] == project["wiki_id"]
    assert project_task.json()["wiki_path"] == "01-Projects/renovate-kitchen/tasks/book-contractor-tsk-book-contractor.md"
    assert (wiki / project_task.json()["wiki_path"]).is_file()

    area_task = client.post(
        "/api/tasks",
        json={
            "title": "Replace filter",
            "task_list_id": task_list["id"],
            "owner_type": "area",
            "owner_wiki_id": area["id"],
        },
    )
    assert area_task.status_code == 201
    assert area_task.json()["owner_type"] == "area"
    assert area_task.json()["wiki_path"] == "02-Areas/house/tasks/replace-filter-tsk-replace-filter.md"


def test_inbox_tasks_have_an_explicit_inbox_owner_and_canonical_path(tmp_path: Path) -> None:
    client, wiki = _client(tmp_path)
    inbox = client.post("/api/task-lists", json={"name": "Inbox"}).json()

    created = client.post(
        "/api/tasks", json={"title": "Capture receipt", "task_list_id": inbox["id"], "owner_type": "inbox"}
    )

    assert created.status_code == 201
    task = created.json()
    assert task["owner_type"] == "inbox"
    assert task["owner_wiki_id"] is None
    assert task["wiki_path"] == "00-Inbox/tasks/capture-receipt-tsk-capture-receipt.md"
    assert (wiki / task["wiki_path"]).is_file()


def test_task_edits_preserve_existing_path_and_reject_owner_reassignment(tmp_path: Path) -> None:
    client, _wiki = _client(tmp_path)
    task_list = client.post("/api/task-lists", json={"name": "Personal"}).json()
    project = client.post("/api/projects", json={"title": "Renovate kitchen"}).json()
    area = client.post("/api/areas", json={"title": "House"}).json()
    created = client.post(
        "/api/tasks",
        json={
            "title": "Book contractor",
            "task_list_id": task_list["id"],
            "owner_type": "project",
            "owner_wiki_id": project["wiki_id"],
        },
    ).json()

    updated = client.patch(
        f"/api/tasks/{created['id']}",
        json={"title": "Book licensed contractor", "expected_hash": created["wiki_hash"]},
    )
    assert updated.status_code == 200
    assert updated.json()["wiki_path"] == created["wiki_path"]

    reassigned = client.patch(
        f"/api/tasks/{created['id']}",
        json={
            "owner_type": "area",
            "owner_wiki_id": area["id"],
            "expected_hash": updated.json()["wiki_hash"],
        },
    )
    assert reassigned.status_code == 409
    assert reassigned.json()["detail"] == "task owner changes require the controlled relocation workflow"


def test_task_ui_selects_canonical_owners_and_displays_owner_and_source_path(tmp_path: Path) -> None:
    client, _wiki = _client(tmp_path)
    task_list = client.post("/api/task-lists", json={"name": "Personal"}).json()
    project = client.post("/api/projects", json={"title": "Renovate kitchen"}).json()

    page = client.get("/")
    assert 'name="owner_type"' in page.text
    assert 'name="owner_wiki_id"' in page.text
    assert project["wiki_id"] in page.text

    created = client.post(
        "/ui/tasks",
        data={
            "title": "Book contractor",
            "task_list_id": str(task_list["id"]),
            "owner_type": "project",
            "owner_wiki_id": project["wiki_id"],
        },
    )
    assert created.status_code == 200
    rendered = client.get("/").text
    assert "Owner: Project · " + project["wiki_id"] in rendered
    assert "Source: 01-Projects/renovate-kitchen/tasks/book-contractor-tsk-book-contractor.md" in rendered


def test_projection_round_trip_keeps_owner_and_rejects_invalid_owner_type(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    project = repository.write("project", "Renovate kitchen", {"id": "prj-kitchen", "status": "active"})
    task = repository.write(
        "task",
        "Book contractor",
        {
            "id": "tsk-book-contractor",
            "status": "open",
            "task_list": "Personal",
            "owner_type": "project",
            "owner_wiki_id": project.record_id,
            "depends_on": [],
        },
        path="01-Projects/renovate-kitchen/tasks/book-contractor-tsk-book-contractor.md",
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'lifeos.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        sync_wiki_projection(session, repository)
        rebuilt = session.scalar(select(Task).where(Task.wiki_id == task.record_id))
        assert rebuilt is not None
        assert rebuilt.owner_type == "project"
        assert rebuilt.owner_wiki_id == project.record_id
        assert reconcile_wiki_projection(session, repository)["invalid_task_owners"] == []

    repository.write(
        "task",
        task.title,
        {**task.fields, "owner_type": "area"},
        path=task.path,
        expected_hash=task.content_hash,
    )
    with factory() as session:
        report = reconcile_wiki_projection(session, repository)
        assert report["invalid_task_owners"] == [
            {"id": task.record_id, "owner_type": "area", "owner_wiki_id": project.record_id, "reason": "owner type mismatch"}
        ]
        assert report["aligned"] is False
        try:
            sync_wiki_projection(session, repository)
        except ValueError as exc:
            assert "invalid task owners" in str(exc)
        else:
            raise AssertionError("projection sync accepted an invalid task owner")
