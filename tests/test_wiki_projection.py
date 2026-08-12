from pathlib import Path

from sqlalchemy import select

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import Goal, Project, Routine, Task, WikiContextItem
from lifeos.scripts_bridge import reconcile_wiki_projection, sync_wiki_projection
from lifeos.wiki_store import WikiRepository


def test_wiki_edit_rebuilds_project_projection(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    path = wiki / "01-Projects/example/index.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\nid: prj-example\ntype: project\nstatus: active\nowner: Brian\n---\n# Example\n\nA canonical project.\n",
        encoding="utf-8",
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'lifeos.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)
    repo = WikiRepository(wiki)
    with factory() as session:
        result = sync_wiki_projection(session, repo)
        assert result["created"] == 1
        project = session.query(Project).one()
        assert project.wiki_id == "prj-example"
        assert project.owner == "Brian"
    path.write_text(
        "---\nid: prj-example\ntype: project\nstatus: paused\nowner: Brian\n---\n# Example\n\nUpdated.\n",
        encoding="utf-8",
    )
    with factory() as session:
        result = sync_wiki_projection(session, repo)
        assert result["updated"] == 1
        assert session.query(Project).one().status == "paused"


def test_projection_rebuild_includes_canonical_areas_in_the_rebuildable_index(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    repo = WikiRepository(wiki)
    area = repo.write(
        "area",
        "House",
        {"id": "area-house", "status": "active", "aliases": ["Home"]},
        "# House\n\nThe home operating area.\n",
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'areas.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        result = sync_wiki_projection(session, repo)
        projected = session.scalar(select(WikiContextItem).where(WikiContextItem.source_id == area.record_id))
        report = reconcile_wiki_projection(session, repo)

        assert result == {"created": 1, "updated": 0, "stale": 0, "unchanged": 0}
        assert projected.source_type == "area"
        assert projected.wiki_path == area.path
        assert projected.content_hash == area.content_hash
        assert projected.stale is False
        assert report["matched_ids"] == [area.record_id]
        assert report["aligned"] is True


def test_projection_rebuild_resolves_relationships_by_stable_wiki_id(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    repo = WikiRepository(wiki)
    goal = repo.write("goal", "Goal", {"id": "goal-one", "status": "active"})
    project = repo.write(
        "project",
        "Project",
        {
            "id": "prj-one",
            "status": "active",
            "collaborators": "Hester",
            "goal_wiki_id": goal.record_id,
        },
    )
    routine = repo.write(
        "routine",
        "Routine",
        {
            "id": "rtn-one",
            "status": "active",
            "cadence": "daily",
            "next_run_date": "2026-08-20",
            "task_list": "Canonical routines",
            "goal_wiki_id": goal.record_id,
            "minimum_occurrences": 2,
            "frequency_window_days": 7,
            "skips": [],
        },
    )
    parent = repo.write(
        "task",
        "Parent",
        {
            "id": "tsk-parent",
            "status": "open",
            "task_list": "Canonical tasks",
            "goal_wiki_id": goal.record_id,
            "project_wiki_id": project.record_id,
            "routine_wiki_id": routine.record_id,
            "depends_on": [],
        },
    )
    child = repo.write(
        "task",
        "Child",
        {
            "id": "tsk-child",
            "status": "open",
            "task_list": "Canonical tasks",
            "goal_wiki_id": goal.record_id,
            "project_wiki_id": project.record_id,
            "routine_wiki_id": routine.record_id,
            "parent_wiki_id": parent.record_id,
            "occurrence_key": "routine:rtn-one:2026-08-20",
            "depends_on": [],
        },
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'relationships.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        sync_wiki_projection(session, repo)
        rebuilt_goal = session.scalar(select(Goal).where(Goal.wiki_id == goal.record_id))
        rebuilt_project = session.scalar(select(Project).where(Project.wiki_id == project.record_id))
        rebuilt_routine = session.scalar(select(Routine).where(Routine.wiki_id == routine.record_id))
        rebuilt_parent = session.scalar(select(Task).where(Task.wiki_id == parent.record_id))
        rebuilt_child = session.scalar(select(Task).where(Task.wiki_id == child.record_id))

        assert rebuilt_project.goal_id == rebuilt_goal.id
        assert rebuilt_project.collaborators == "Hester"
        assert rebuilt_routine.goal_id == rebuilt_goal.id
        assert rebuilt_routine.minimum_occurrences == 2
        assert rebuilt_routine.frequency_window_days == 7
        assert rebuilt_routine.task_list.name == "Canonical routines"
        assert rebuilt_parent.goal_id == rebuilt_goal.id
        assert rebuilt_parent.project_id == rebuilt_project.id
        assert rebuilt_parent.routine_id == rebuilt_routine.id
        assert rebuilt_child.parent_id == rebuilt_parent.id
        assert rebuilt_child.goal_id == rebuilt_goal.id
        assert rebuilt_child.project_id == rebuilt_project.id
        assert rebuilt_child.routine_id == rebuilt_routine.id
        assert rebuilt_child.occurrence_key == "routine:rtn-one:2026-08-20"
