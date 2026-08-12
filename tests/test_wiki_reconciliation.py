from pathlib import Path

import pytest

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import Goal, Project
from lifeos.scripts_bridge import reconcile_wiki_projection, sync_wiki_projection
from lifeos.wiki_store import WikiRepository, render_frontmatter


def test_reconciliation_reports_missing_orphaned_and_hash_conflicts(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    project = repository.write("project", "Canonical Project", {"status": "active"}, "# Canonical Project\n")
    engine = create_engine(f"sqlite:///{tmp_path / 'lifeos.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        sync_wiki_projection(session, repository)
        assert reconcile_wiki_projection(session, repository)["aligned"] is True
        path = wiki / project.path
        path.write_text(path.read_text(encoding="utf-8") + "\nExternal edit.\n", encoding="utf-8")
        report = reconcile_wiki_projection(session, repository)
        assert report["hash_conflicts"] == [project.record_id]
        assert report["aligned"] is False


def test_reconciliation_reports_identity_path_and_type_discrepancies(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    canonical = repository.write(
        "project",
        "Canonical Project",
        {"id": "prj-canonical", "status": "active"},
        "# Canonical Project\n",
    )
    missing = repository.write(
        "goal",
        "Missing Projection",
        {"id": "goal-missing", "status": "active"},
        "# Missing Projection\n",
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'report.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        sync_wiki_projection(session, repository)
        missing_projection = session.query(Goal).filter_by(wiki_id=missing.record_id).one()
        session.delete(missing_projection)
        projected = session.query(Project).filter_by(wiki_id=canonical.record_id).one()
        projected.wiki_path = "01-Projects/wrong/index.md"
        session.add(Goal(title="Wrong type", wiki_id=canonical.record_id, wiki_path=canonical.path, wiki_hash=canonical.content_hash))
        session.add(Project(title="No identity"))
        session.add(Project(title="Orphan", wiki_id="prj-orphan", wiki_path=canonical.path, wiki_hash="0" * 64))
        session.add(Project(title="Missing source", wiki_id="prj-missing-source", wiki_path="01-Projects/missing/index.md"))
        session.commit()

        duplicate = wiki / "01-Projects/LifeOS/lifeos/projects/duplicate-id.md"
        duplicate.parent.mkdir(parents=True, exist_ok=True)
        duplicate.write_text(
            render_frontmatter(
                {"schema_version": "1", "id": canonical.record_id, "type": "project", "title": "Duplicate ID"},
                "# Duplicate ID\n",
            ),
            encoding="utf-8",
        )

        report = reconcile_wiki_projection(session, repository)

    assert report["matched_ids"] == [canonical.record_id]
    assert report["missing_projection"] == [missing.record_id]
    assert report["orphaned_projection"] == ["prj-missing-source", "prj-orphan"]
    assert report["duplicate_source_ids"] == {
        canonical.record_id: sorted([canonical.path, duplicate.relative_to(wiki).as_posix()])
    }
    assert report["duplicate_projection_ids"] == {canonical.record_id: ["goal", "project"]}
    assert report["duplicate_projection_paths"] == {canonical.path: ["goal:2", "project:3"]}
    assert report["missing_identity"] == ["project:2"]
    assert report["type_conflicts"] == [{"id": canonical.record_id, "projection_type": "goal", "source_type": "project"}]
    assert report["path_conflicts"] == [canonical.record_id]
    assert report["invalid_links"] == [
        {
            "id": canonical.record_id,
            "path": "01-Projects/wrong/index.md",
            "status": "missing",
            "diagnostic": "Canonical wiki source is missing",
        },
        {
            "id": "prj-missing-source",
            "path": "01-Projects/missing/index.md",
            "status": "missing",
            "diagnostic": "Canonical wiki source is missing",
        },
    ]
    assert report["aligned"] is False


def test_projection_sync_refuses_duplicate_canonical_ids_before_mutation(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    first = repository.write(
        "goal",
        "First Goal",
        {"id": "goal-duplicate", "status": "active"},
        "# First Goal\n",
    )
    duplicate = wiki / "01-Projects/LifeOS/lifeos/goals/second-goal.md"
    duplicate.parent.mkdir(parents=True, exist_ok=True)
    duplicate.write_text(
        render_frontmatter(
            {"schema_version": "1", "id": first.record_id, "type": "goal", "title": "Second Goal"},
            "# Second Goal\n",
        ),
        encoding="utf-8",
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'duplicates.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        with pytest.raises(ValueError, match="duplicate canonical wiki IDs"):
            sync_wiki_projection(session, repository)
        assert session.query(Goal).count() == 0


def test_projection_sync_never_adopts_legacy_rows_by_title(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    canonical = repository.write(
        "project",
        "Repeated Title",
        {"id": "prj-repeated-title", "status": "active"},
        "# Repeated Title\n",
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-title.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        legacy = Project(title="Repeated Title", status="paused")
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id

        result = sync_wiki_projection(session, repository)

        rows = session.query(Project).order_by(Project.id).all()
        assert result["created"] == 1
        assert len(rows) == 2
        assert rows[0].id == legacy_id
        assert rows[0].wiki_id is None
        assert rows[0].status == "paused"
        assert rows[1].wiki_id == canonical.record_id
        assert rows[1].wiki_path == canonical.path
        assert reconcile_wiki_projection(session, repository)["missing_identity"] == [f"project:{legacy_id}"]


def test_reconciliation_reports_and_sync_refuses_unresolved_canonical_relationships(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    task = repository.write(
        "task",
        "Broken links",
        {
            "id": "tsk-broken-links",
            "status": "open",
            "task_list": "Inbox",
            "project_wiki_id": "prj-missing",
            "depends_on": ["tsk-missing"],
        },
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'broken-links.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        report = reconcile_wiki_projection(session, repository)
        assert report["unresolved_relationships"] == [
            {
                "id": task.record_id,
                "field": "depends_on",
                "target_id": "tsk-missing",
                "expected_type": "task",
            },
            {
                "id": task.record_id,
                "field": "project_wiki_id",
                "target_id": "prj-missing",
                "expected_type": "project",
            },
        ]
        assert report["aligned"] is False
        with pytest.raises(ValueError, match="unresolved canonical relationships"):
            sync_wiki_projection(session, repository)
        assert session.query(Project).count() == 0
