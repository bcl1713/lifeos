import json
from pathlib import Path

import pytest
from sqlalchemy import select

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import Task
from lifeos.scripts_bridge import sync_wiki_projection
from lifeos.task_relocation import (
    RelocationError,
    inventory_task_ownership,
    recover_relocations,
    relocate_tasks,
)
from lifeos.wiki_store import WikiRepository


def _session_factory(tmp_path: Path, name: str = "lifeos.db"):
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    initialize_database(engine)
    return create_session_factory(engine)


def _records(tmp_path: Path):
    repository = WikiRepository(tmp_path / "wiki")
    project = repository.write("project", "Kitchen", {"id": "prj-kitchen", "status": "active"})
    area = repository.write("area", "Home", {"id": "area-home", "status": "active"})
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
        path="01-Projects/LifeOS/lifeos/tasks/book-contractor-tsk-book-contractor.md",
    )
    return repository, project, area, task


def _mapping(task, owner, owner_type: str = "area") -> dict:
    return {
        "source_id": task.record_id,
        "source_path": task.path,
        "source_hash": task.content_hash,
        "owner_type": owner_type,
        "owner_wiki_id": owner.record_id,
        "owner_path": owner.path,
    }


def test_inventory_and_dry_run_report_complete_task_state_without_writes(tmp_path: Path) -> None:
    repository, project, area, task = _records(tmp_path)
    factory = _session_factory(tmp_path)
    before = (repository.root / task.path).read_text(encoding="utf-8")
    journal_dir = tmp_path / "journals"

    inventory = inventory_task_ownership(repository)
    with factory() as session:
        result = relocate_tasks(session, repository, [_mapping(task, area)], journal_dir=journal_dir, apply=False)

    assert inventory["tasks"] == [
        {
            "id": task.record_id,
            "path": task.path,
            "hash": task.content_hash,
            "owner_type": "project",
            "owner_wiki_id": project.record_id,
            "task_list": "Personal",
            "relationships": {
                "depends_on": [],
                "goal_wiki_id": None,
                "parent_wiki_id": None,
                "project_wiki_id": None,
                "routine_wiki_id": None,
            },
            "owner_candidate": {
                "owner_type": "project",
                "owner_wiki_id": project.record_id,
                "owner_path": project.path,
            },
            "target_path": "01-Projects/kitchen/tasks/book-contractor-tsk-book-contractor.md",
            "issues": ["task path does not match owner target"],
        }
    ]
    assert result["apply"] is False
    assert result["planned"] == 1
    assert (repository.root / task.path).read_text(encoding="utf-8") == before
    assert not journal_dir.exists()


def test_relocation_requires_explicit_verified_mapping_and_rejects_destination_conflicts(tmp_path: Path) -> None:
    repository, _project, area, task = _records(tmp_path)
    factory = _session_factory(tmp_path)
    mapping = _mapping(task, area)
    mapping["owner_path"] = "02-Areas/guessed/index.md"

    with factory() as session:
        with pytest.raises(RelocationError, match="owner path"):
            relocate_tasks(
                session,
                repository,
                [mapping],
                journal_dir=tmp_path / "journals",
                apply=True,
                backup_dir=tmp_path / "backups",
            )

    mapping = _mapping(task, area)
    destination = repository.task_path(area, task.title, task.record_id)
    repository.write(
        "task",
        "Conflict",
        {"id": "tsk-conflict", "status": "open", "task_list": "Inbox", "owner_type": "inbox"},
        path=destination,
    )
    with factory() as session:
        with pytest.raises(RelocationError, match="destination already exists"):
            relocate_tasks(
                session,
                repository,
                [mapping],
                journal_dir=tmp_path / "journals",
                apply=True,
                backup_dir=tmp_path / "backups",
            )


def test_same_owner_target_is_a_noop_and_duplicate_active_ids_are_rejected(tmp_path: Path) -> None:
    repository, project, _area, task = _records(tmp_path)
    factory = _session_factory(tmp_path)
    destination = repository.task_path(project, task.title, task.record_id)
    repository.root.joinpath(destination).parent.mkdir(parents=True, exist_ok=True)
    repository.root.joinpath(task.path).replace(repository.root / destination)
    moved = repository.read(destination)
    mapping = _mapping(moved, project, "project")

    with factory() as session:
        result = relocate_tasks(
            session,
            repository,
            [mapping],
            journal_dir=tmp_path / "journals",
            apply=True,
            backup_dir=tmp_path / "backups",
        )
    assert result["unchanged"] == [task.record_id]

    duplicate = repository.root / "01-Projects/LifeOS/lifeos/tasks/duplicate.md"
    duplicate.write_text((repository.root / destination).read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(RelocationError, match="duplicate active canonical task IDs"):
        inventory_task_ownership(repository)


def test_relocation_moves_source_then_refreshes_projection_and_fresh_rebuild(tmp_path: Path) -> None:
    repository, _project, area, task = _records(tmp_path)
    factory = _session_factory(tmp_path)
    mapping = _mapping(task, area)

    with factory() as session:
        result = relocate_tasks(
            session,
            repository,
            [mapping],
            journal_dir=tmp_path / "journals",
            apply=True,
            backup_dir=tmp_path / "backups",
        )
        projected = session.scalar(select(Task).where(Task.wiki_id == task.record_id))
        assert result["relocated"] == [task.record_id]
        assert projected is not None
        assert projected.owner_type == "area"
        assert projected.owner_wiki_id == area.record_id
        assert projected.wiki_path == repository.task_path(area, task.title, task.record_id)

    assert not (repository.root / task.path).exists()
    read_back = repository.read(repository.task_path(area, task.title, task.record_id))
    assert read_back.record_id == task.record_id
    assert read_back.fields["owner_type"] == "area"
    assert read_back.fields["owner_wiki_id"] == area.record_id

    fresh_factory = _session_factory(tmp_path, "fresh.db")
    with fresh_factory() as session:
        sync_wiki_projection(session, repository)
        rebuilt = session.scalar(select(Task).where(Task.wiki_id == task.record_id))
        assert rebuilt is not None
        assert rebuilt.wiki_path == read_back.path
        assert rebuilt.owner_wiki_id == area.record_id


def test_interrupted_relocation_recovers_idempotently_from_journal(tmp_path: Path, monkeypatch) -> None:
    repository, _project, area, task = _records(tmp_path)
    factory = _session_factory(tmp_path)
    journal_dir = tmp_path / "journals"
    mapping = _mapping(task, area)

    def interrupted(*_args, **_kwargs):
        raise RuntimeError("projection interrupted")

    monkeypatch.setattr("lifeos.task_relocation.sync_wiki_projection", interrupted)
    with factory() as session:
        with pytest.raises(RuntimeError, match="projection interrupted"):
            relocate_tasks(
                session, repository, [mapping], journal_dir=journal_dir, apply=True, backup_dir=tmp_path / "backups"
            )

    assert not (repository.root / task.path).exists()
    assert repository.read(repository.task_path(area, task.title, task.record_id)).record_id == task.record_id
    journal = json.loads(next(journal_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert journal["state"] == "source_moved"
    monkeypatch.setattr("lifeos.task_relocation.sync_wiki_projection", sync_wiki_projection)

    with factory() as session:
        recovered = recover_relocations(session, repository, journal_dir=journal_dir)
        assert recovered == [task.record_id]
        projected = session.scalar(select(Task).where(Task.wiki_id == task.record_id))
        assert projected is not None
        assert projected.wiki_path == repository.task_path(area, task.title, task.record_id)

    with factory() as session:
        assert recover_relocations(session, repository, journal_dir=journal_dir) == []
