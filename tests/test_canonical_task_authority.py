from pathlib import Path

from fastapi.testclient import TestClient

from lifeos.domain import Task
from lifeos.main import create_app
from lifeos.scripts_bridge import sync_wiki_projection
from lifeos.wiki_store import WikiRepository


def test_new_task_identity_is_created_by_canonical_wiki_before_projection(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Inbox"}).json()

    created = client.post("/api/tasks", json={"title": "Canonical identity", "task_list_id": task_list["id"]})

    assert created.status_code == 201
    task = created.json()
    assert task["wiki_id"] == "tsk-canonical-identity"
    assert task["wiki_id"] != f"tsk-{task['id']}"
    assert (wiki / task["wiki_path"]).is_file()


def test_empty_projection_rebuild_preserves_canonical_task_identity_and_list_name(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    record = repository.write(
        "task",
        "Rebuild me",
        {
            "id": "tsk-rebuild-me",
            "status": "open",
            "task_list": "Household",
            "priority": 2,
            "tags": ["home"],
        },
    )
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )

    with app.state.session_factory() as session:
        result = sync_wiki_projection(session, repository)
        task = session.query(Task).one()
        assert result["created"] == 1
        assert task.wiki_id == record.record_id
        assert task.task_list.name == "Household"
        assert task.tags == '["home"]'
