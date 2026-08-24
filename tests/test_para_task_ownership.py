from pathlib import Path

import pytest
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


def test_task_list_updates_reject_inbox_owner_outside_inbox_and_keep_compatible_owners(tmp_path: Path) -> None:
    client, wiki = _client(tmp_path)
    inbox = client.post("/api/task-lists", json={"name": "Inbox"}).json()
    personal = client.post("/api/task-lists", json={"name": "Personal"}).json()
    errands = client.post("/api/task-lists", json={"name": "Errands"}).json()
    project = client.post("/api/projects", json={"title": "Renovate kitchen"}).json()
    area = client.post("/api/areas", json={"title": "House"}).json()

    inbox_task = client.post(
        "/api/tasks", json={"title": "Capture receipt", "task_list_id": inbox["id"], "owner_type": "inbox"}
    ).json()
    canonical_before = (wiki / inbox_task["wiki_path"]).read_text()
    rejected = client.patch(
        f"/api/tasks/{inbox_task['id']}",
        json={"task_list_id": personal["id"], "expected_hash": inbox_task["wiki_hash"]},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "Inbox ownership requires the Inbox task list and no owner_wiki_id"
    persisted = next(task for task in client.get("/api/tasks").json() if task["id"] == inbox_task["id"])
    assert persisted["task_list_id"] == inbox["id"]
    assert persisted["owner_type"] == "inbox"
    assert persisted["wiki_hash"] == inbox_task["wiki_hash"]
    assert (wiki / inbox_task["wiki_path"]).read_text() == canonical_before

    project_task = client.post(
        "/api/tasks",
        json={
            "title": "Book contractor",
            "task_list_id": personal["id"],
            "owner_type": "project",
            "owner_wiki_id": project["wiki_id"],
        },
    ).json()
    updated = client.patch(
        f"/api/tasks/{project_task['id']}",
        json={"task_list_id": errands["id"], "expected_hash": project_task["wiki_hash"]},
    )
    assert updated.status_code == 200
    assert updated.json()["task_list_id"] == errands["id"]
    assert updated.json()["owner_type"] == "project"
    assert updated.json()["owner_wiki_id"] == project["wiki_id"]

    area_task = client.post(
        "/api/tasks",
        json={
            "title": "Replace filter",
            "task_list_id": personal["id"],
            "owner_type": "area",
            "owner_wiki_id": area["id"],
        },
    ).json()
    area_updated = client.patch(
        f"/api/tasks/{area_task['id']}",
        json={"task_list_id": errands["id"], "expected_hash": area_task["wiki_hash"]},
    )
    assert area_updated.status_code == 200
    assert area_updated.json()["task_list_id"] == errands["id"]
    assert area_updated.json()["owner_type"] == "area"
    assert area_updated.json()["owner_wiki_id"] == area["id"]


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


def test_task_ui_fences_projected_task_owner_controls(tmp_path: Path) -> None:
    client, _wiki = _client(tmp_path)
    page = client.get("/")

    assert page.status_code == 200
    assert 'name="task_owner"' not in page.text
    assert '<fieldset class="task-owner">' not in page.text
    assert "/ui/tasks/" not in page.text
    assert "Checkbox state is read-only in LifeOS" in page.text


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


def test_projection_rejects_unowned_non_inbox_canonical_task(tmp_path: Path) -> None:
    repository = WikiRepository(tmp_path / "wiki")
    task = repository.write(
        "task",
        "Unowned personal task",
        {"id": "tsk-unowned-personal", "status": "open", "task_list": "Personal", "depends_on": []},
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'lifeos.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        report = reconcile_wiki_projection(session, repository)
        assert report["invalid_task_owners"] == [
            {
                "id": task.record_id,
                "owner_type": "",
                "owner_wiki_id": "",
                "reason": "owner fields are incomplete or Inbox is invalid",
            }
        ]
        assert report["aligned"] is False
        try:
            sync_wiki_projection(session, repository)
        except ValueError as exc:
            assert "invalid task owners" in str(exc)
        else:
            raise AssertionError("projection sync accepted an unowned non-Inbox task")


def _corrupt_task_list_projection(client: TestClient, task_id: int, task_list_id: int) -> None:
    with client.app.state.session_factory() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.task_list_id = task_list_id
        session.commit()


def _task_by_id(client: TestClient, task_id: int) -> dict:
    return next(task for task in client.get("/api/tasks").json() if task["id"] == task_id)


@pytest.mark.parametrize("mutation", ["api_status", "ui_status", "add_dependency"])
def test_invalid_persisted_owner_rejects_writes_without_mutating_canonical_or_projection(
    tmp_path: Path, mutation: str
) -> None:
    client, wiki = _client(tmp_path)
    inbox = client.post("/api/task-lists", json={"name": "Inbox"}).json()
    personal = client.post("/api/task-lists", json={"name": "Personal"}).json()
    task = client.post("/api/tasks", json={"title": "Capture receipt", "task_list_id": inbox["id"]}).json()
    prerequisite = client.post("/api/tasks", json={"title": "Prerequisite", "task_list_id": inbox["id"]}).json()
    canonical_before = (wiki / task["wiki_path"]).read_text()
    _corrupt_task_list_projection(client, task["id"], personal["id"])

    if mutation == "api_status":
        response = client.post(f"/api/tasks/{task['id']}/complete", params={"expected_hash": task["wiki_hash"]})
    elif mutation == "ui_status":
        response = client.post(f"/ui/tasks/{task['id']}/complete", data={"expected_hash": task["wiki_hash"]})
    else:
        response = client.post(
            f"/api/tasks/{task['id']}/dependencies",
            json={"depends_on_task_id": prerequisite["id"], "expected_hash": task["wiki_hash"]},
        )

    assert response.status_code == 422
    persisted = _task_by_id(client, task["id"])
    assert persisted["task_list_id"] == personal["id"]
    assert persisted["status"] == "open"
    assert persisted["wiki_path"] == task["wiki_path"]
    assert persisted["wiki_hash"] == task["wiki_hash"]
    assert (wiki / task["wiki_path"]).read_text() == canonical_before
    assert client.get(f"/api/tasks/{task['id']}/dependencies").json() == []


def test_invalid_persisted_owner_rejects_dependency_removal_without_mutation(tmp_path: Path) -> None:
    client, wiki = _client(tmp_path)
    inbox = client.post("/api/task-lists", json={"name": "Inbox"}).json()
    personal = client.post("/api/task-lists", json={"name": "Personal"}).json()
    task = client.post("/api/tasks", json={"title": "Capture receipt", "task_list_id": inbox["id"]}).json()
    prerequisite = client.post("/api/tasks", json={"title": "Prerequisite", "task_list_id": inbox["id"]}).json()
    added = client.post(
        f"/api/tasks/{task['id']}/dependencies",
        json={"depends_on_task_id": prerequisite["id"], "expected_hash": task["wiki_hash"]},
    ).json()
    current = _task_by_id(client, task["id"])
    canonical_before = (wiki / current["wiki_path"]).read_text()
    _corrupt_task_list_projection(client, task["id"], personal["id"])

    response = client.delete(
        f"/api/tasks/{task['id']}/dependencies/{added['id']}", params={"expected_hash": current["wiki_hash"]}
    )

    assert response.status_code == 422
    persisted = _task_by_id(client, task["id"])
    assert persisted["task_list_id"] == personal["id"]
    assert persisted["wiki_hash"] == current["wiki_hash"]
    assert (wiki / current["wiki_path"]).read_text() == canonical_before
    assert [item["id"] for item in client.get(f"/api/tasks/{task['id']}/dependencies").json()] == [added["id"]]


@pytest.mark.parametrize("owner_type", ["project", "area"])
def test_valid_para_owned_task_status_write_remains_supported(tmp_path: Path, owner_type: str) -> None:
    client, wiki = _client(tmp_path)
    personal = client.post("/api/task-lists", json={"name": "Personal"}).json()
    owner = client.post(f"/api/{owner_type}s", json={"title": "Renovate kitchen"}).json()
    task = client.post(
        "/api/tasks",
        json={
            "title": "Book contractor",
            "task_list_id": personal["id"],
            "owner_type": owner_type,
            "owner_wiki_id": owner["wiki_id"] if owner_type == "project" else owner["id"],
        },
    ).json()

    completed = client.post(f"/api/tasks/{task['id']}/complete", params={"expected_hash": task["wiki_hash"]})

    assert completed.status_code == 200
    assert completed.json()["owner_type"] == owner_type
    assert completed.json()["owner_wiki_id"] == task["owner_wiki_id"]
    assert (wiki / completed.json()["wiki_path"]).is_file()
