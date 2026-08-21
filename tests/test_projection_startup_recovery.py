from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import Project, Task
from lifeos.main import create_app
from lifeos.scripts_bridge import reconcile_wiki_projection, sync_wiki_projection
from lifeos.wiki_store import WikiRepository, render_frontmatter


ARCHIVED_PROJECT_ID = "prj-acceptance-project-20260813t001536z"
ACTIVE_TASK_ID = "tsk-acceptance-task-20260813t001536z"


def _write_incident_fixture(wiki: Path, *, project_id: str = ARCHIVED_PROJECT_ID) -> WikiRepository:
    repository = WikiRepository(wiki)
    archived_project = wiki / "04-Archives" / "projects" / "acceptance-project.md"
    archived_project.parent.mkdir(parents=True)
    archived_project.write_text(
        render_frontmatter(
            {
                "schema_version": "1",
                "id": project_id,
                "type": "project",
                "title": "Acceptance project",
                "status": "archived",
            },
            "# Acceptance project\n",
        ),
        encoding="utf-8",
    )
    repository.write(
        "task",
        "Acceptance task",
        {
            "id": ACTIVE_TASK_ID,
            "status": "open",
            "task_list": "Inbox",
            "project_wiki_id": project_id,
        },
    )
    return repository


def test_startup_rebuild_accepts_active_task_link_to_archived_project(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    repository = _write_incident_fixture(wiki)
    database_url = f"sqlite:///{tmp_path / 'lifeos.db'}"
    assert [record.record_id for record in repository.list_records("project")] == [ARCHIVED_PROJECT_ID]
    engine = create_engine(database_url)
    initialize_database(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        result = sync_wiki_projection(session, repository)
        task = session.scalar(select(Task).where(Task.wiki_id == ACTIVE_TASK_ID))
        project = session.scalar(select(Project).where(Project.wiki_id == ARCHIVED_PROJECT_ID))

        assert result == {"created": 2, "updated": 0, "stale": 0, "unchanged": 0}
        assert project is not None
        assert project.status == "archived"
        assert task is not None
        assert task.project_id == project.id
        assert reconcile_wiki_projection(session, repository)["aligned"] is True

    app = create_app(database_url=database_url, scheduler_enabled=False, wiki_root=str(wiki))
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_startup_rebuild_refuses_missing_project_with_actionable_relationship_diagnostic(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    repository = _write_incident_fixture(wiki, project_id="prj-missing-acceptance-project")
    engine = create_engine(f"sqlite:///{tmp_path / 'missing.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        (wiki / "04-Archives" / "projects" / "acceptance-project.md").unlink()

        report = reconcile_wiki_projection(session, repository)
        assert report["unresolved_relationships"] == [
            {
                "id": ACTIVE_TASK_ID,
                "field": "project_wiki_id",
                "target_id": "prj-missing-acceptance-project",
                "expected_type": "project",
            }
        ]
        with pytest.raises(
            ValueError,
            match=(
                "unresolved canonical relationships: "
                "tsk-acceptance-task-20260813t001536z.project_wiki_id "
                "-> prj-missing-acceptance-project \\(project\\)"
            ),
        ):
            sync_wiki_projection(session, repository)
        assert session.query(Project).count() == 0
        assert session.query(Task).count() == 0
