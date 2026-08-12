from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import Goal, GoalMilestone, Project, Routine, RoutineSkip, Task, TaskDependency, TaskList
from lifeos.scripts_bridge import sync_wiki_projection
from lifeos.wiki_store import WikiRepository
from scripts.canonicalize_legacy_projection import canonicalize_legacy_projection


def test_legacy_projection_canonicalization_is_dry_run_idempotent_and_rebuildable(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    existing = repository.write("goal", "Existing", {"id": "goal-existing", "status": "active", "milestones": []})
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)

    with factory() as session:
        task_list = TaskList(name="Legacy Inbox")
        existing_goal = Goal(title="Existing", wiki_id=existing.record_id, wiki_path=existing.path, wiki_hash=existing.content_hash)
        goal = Goal(title="Repeated title", status="active", outcome="Preserve outcome")
        session.add_all([task_list, existing_goal, goal])
        session.flush()
        milestone = GoalMilestone(
            goal_id=goal.id,
            title="First milestone",
            status="completed",
            due_date=date(2026, 9, 1),
            completed_at=datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc),
        )
        project = Project(title="Repeated title", status="paused", goal_id=goal.id, scope="Preserve scope", wiki_id="")
        routine = Routine(
            title="Repeated title",
            cadence="weekly",
            status="paused",
            next_run_date=date(2026, 8, 20),
            task_list_id=task_list.id,
            goal_id=goal.id,
            minimum_occurrences=2,
            frequency_window_days=7,
        )
        session.add_all([milestone, project, routine])
        session.flush()
        skip = RoutineSkip(routine_id=routine.id, scheduled_date=date(2026, 8, 27), reason="Away")
        parent = Task(
            title="Repeated title",
            notes="Parent notes",
            status="completed",
            priority=2,
            tags='["legacy"]',
            source_ref="google:parent",
            due_date=date(2026, 8, 19),
            task_list_id=task_list.id,
            goal_id=goal.id,
            project_id=project.id,
            routine_id=routine.id,
            occurrence_key="routine:legacy:2026-08-19",
        )
        session.add_all([skip, parent])
        session.flush()
        child = Task(
            title="Repeated title",
            status="open",
            task_list_id=task_list.id,
            goal_id=goal.id,
            project_id=project.id,
            routine_id=routine.id,
            parent_id=parent.id,
        )
        session.add(child)
        session.flush()
        session.add(TaskDependency(task_id=child.id, depends_on_task_id=parent.id))
        session.commit()
        ids = {"goal": goal.id, "project": project.id, "routine": routine.id, "parent": parent.id, "child": child.id}

        dry_run = canonicalize_legacy_projection(session, repository, apply=False)
        assert dry_run["planned"] == {"goal": 1, "project": 1, "routine": 1, "task": 2}
        assert [(record.record_id, record.path) for record in repository.list_records()] == [
            (existing.record_id, existing.path)
        ]
        assert session.get(Task, parent.id).wiki_id is None

        applied = canonicalize_legacy_projection(session, repository, apply=True)
        assert applied["created"] == {"goal": 1, "project": 1, "routine": 1, "task": 2}
        assert applied["remaining_missing_identity"] == 0
        rerun = canonicalize_legacy_projection(session, repository, apply=True)
        assert rerun["created"] == {"goal": 0, "project": 0, "routine": 0, "task": 0}
        assert rerun["unchanged"] == 6

        assert session.get(Goal, ids["goal"]).wiki_id == f"goal-legacy-{ids['goal']}"
        assert session.get(Project, ids["project"]).wiki_id == f"prj-legacy-{ids['project']}"
        assert session.get(Routine, ids["routine"]).wiki_id == f"rtn-legacy-{ids['routine']}"
        assert session.get(Task, ids["parent"]).wiki_id == f"tsk-legacy-{ids['parent']}"
        child_record = repository.find_by_id(f"tsk-legacy-{ids['child']}")
        assert child_record.fields["parent_wiki_id"] == f"tsk-legacy-{ids['parent']}"
        assert child_record.fields["depends_on"] == [f"tsk-legacy-{ids['parent']}"]
        assert child_record.fields["migration_source"] == {"table": "tasks", "row_id": ids["child"]}

        sync_wiki_projection(session, repository)
        assert session.scalar(select(GoalMilestone).where(GoalMilestone.goal_id == goal.id)).status == "completed"
        assert len(list(session.scalars(select(RoutineSkip).where(RoutineSkip.routine_id == routine.id)))) == 1
        assert len(list(session.scalars(select(TaskDependency).where(TaskDependency.task_id == child.id)))) == 1
        assert session.scalar(select(Task).where(Task.occurrence_key == "routine:legacy:2026-08-19")).id == parent.id

    rebuilt_engine = create_engine(f"sqlite:///{tmp_path / 'rebuilt.db'}")
    initialize_database(rebuilt_engine)
    rebuilt_factory = create_session_factory(rebuilt_engine)
    with rebuilt_factory() as session:
        sync_wiki_projection(session, repository)
        rebuilt_goal = session.scalar(select(Goal).where(Goal.wiki_id == f"goal-legacy-{ids['goal']}"))
        rebuilt_project = session.scalar(select(Project).where(Project.wiki_id == f"prj-legacy-{ids['project']}"))
        rebuilt_routine = session.scalar(select(Routine).where(Routine.wiki_id == f"rtn-legacy-{ids['routine']}"))
        rebuilt_parent = session.scalar(select(Task).where(Task.wiki_id == f"tsk-legacy-{ids['parent']}"))
        rebuilt_child = session.scalar(select(Task).where(Task.wiki_id == f"tsk-legacy-{ids['child']}"))
        assert rebuilt_project.goal_id == rebuilt_goal.id
        assert rebuilt_routine.goal_id == rebuilt_goal.id
        assert rebuilt_routine.skips[0].reason == "Away"
        assert rebuilt_goal.milestones[0].status == "completed"
        assert rebuilt_goal.milestones[0].completed_at is not None
        assert rebuilt_parent.occurrence_key == "routine:legacy:2026-08-19"
        assert rebuilt_child.parent_id == rebuilt_parent.id
        edge = session.scalar(select(TaskDependency).where(TaskDependency.task_id == rebuilt_child.id))
        assert edge.depends_on_task_id == rebuilt_parent.id
