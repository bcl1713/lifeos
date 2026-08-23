import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import Task
from lifeos.scripts_bridge import sync_wiki_projection
from lifeos.task_relocation import (
    RelocationError,
    _wiki_snapshot_hash,
    create_verified_backup_evidence,
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


def _backup_evidence(tmp_path: Path, repository: WikiRepository, database_target: str = "sqlite:///target.db") -> Path:
    sequence = len(list(tmp_path.glob("verified-backup-*.json")))
    return create_verified_backup_evidence(
        repository,
        database=tmp_path / "lifeos.db",
        database_target=database_target,
        evidence_path=tmp_path / f"verified-backup-{sequence}.json",
        wiki_backup_path=tmp_path / f"wiki-backup-{sequence}.tar",
        sqlite_backup_path=tmp_path / f"lifeos-backup-{sequence}.db",
    )


def _forged_backup_evidence(
    tmp_path: Path, repository: WikiRepository, database_target: str = "sqlite:///target.db"
) -> Path:
    wiki_backup = tmp_path / "forged-wiki-backup.tar"
    sqlite_backup = tmp_path / "forged-lifeos-backup.db"
    wiki_backup.write_bytes(b"verified wiki backup")
    sqlite_backup.write_bytes(b"verified sqlite backup")
    evidence = tmp_path / "forged-verified-backup.json"
    evidence.write_text(
        json.dumps(
            {
                "version": 2,
                "wiki_root": str(repository.root.resolve()),
                "wiki_snapshot_sha256": _wiki_snapshot_hash(repository.root.resolve()),
                "database": database_target,
                "wiki_backup": {
                    "path": str(wiki_backup),
                    "sha256": hashlib.sha256(wiki_backup.read_bytes()).hexdigest(),
                },
                "sqlite_backup": {
                    "path": str(sqlite_backup),
                    "sha256": hashlib.sha256(sqlite_backup.read_bytes()).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )
    return evidence


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
                backup_evidence=_backup_evidence(tmp_path, repository),
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
                backup_evidence=_backup_evidence(tmp_path, repository),
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
            backup_evidence=_backup_evidence(tmp_path, repository),
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
            backup_evidence=_backup_evidence(tmp_path, repository),
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
    evidence = _backup_evidence(tmp_path, repository)
    mapping = _mapping(task, area)

    def interrupted(*_args, **_kwargs):
        raise RuntimeError("projection interrupted")

    monkeypatch.setattr("lifeos.task_relocation.sync_wiki_projection", interrupted)
    with factory() as session:
        with pytest.raises(RuntimeError, match="projection interrupted"):
            relocate_tasks(
                session,
                repository,
                [mapping],
                journal_dir=journal_dir,
                apply=True,
                backup_dir=tmp_path / "backups",
                backup_evidence=evidence,
            )

    assert not (repository.root / task.path).exists()
    assert repository.read(repository.task_path(area, task.title, task.record_id)).record_id == task.record_id
    journal = json.loads(next(journal_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert journal["state"] == "source_moved"
    monkeypatch.setattr("lifeos.task_relocation.sync_wiki_projection", sync_wiki_projection)

    with factory() as session:
        recovered = recover_relocations(session, repository, journal_dir=journal_dir, backup_evidence=evidence)
        assert recovered == [task.record_id]
        projected = session.scalar(select(Task).where(Task.wiki_id == task.record_id))
        assert projected is not None
        assert projected.wiki_path == repository.task_path(area, task.title, task.record_id)

    with factory() as session:
        assert (
            recover_relocations(
                session, repository, journal_dir=journal_dir, backup_evidence=_backup_evidence(tmp_path, repository)
            )
            == []
        )


def test_apply_requires_valid_target_bound_verified_backup_evidence(tmp_path: Path) -> None:
    repository, _project, area, task = _records(tmp_path)
    factory = _session_factory(tmp_path)
    backup_dir = tmp_path / "source-backups"

    with factory() as session:
        with pytest.raises(RelocationError, match="verified backup evidence"):
            relocate_tasks(
                session,
                repository,
                [_mapping(task, area)],
                journal_dir=tmp_path / "journals",
                apply=True,
                backup_dir=backup_dir,
            )
    assert not backup_dir.exists()
    assert not (tmp_path / "journals").exists()

    evidence = _backup_evidence(tmp_path, repository)
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["wiki_root"] = str(tmp_path / "another-wiki")
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    with factory() as session:
        with pytest.raises(RelocationError, match="wiki root"):
            relocate_tasks(
                session,
                repository,
                [_mapping(task, area)],
                journal_dir=tmp_path / "journals",
                apply=True,
                backup_dir=backup_dir,
                backup_evidence=evidence,
            )
    assert not backup_dir.exists()
    assert not (tmp_path / "journals").exists()

    evidence = _backup_evidence(tmp_path, repository)
    backup_path = Path(json.loads(evidence.read_text(encoding="utf-8"))["wiki_backup"]["path"])
    backup_path.write_bytes(b"tampered backup")
    with factory() as session:
        with pytest.raises(RelocationError, match="hash does not match"):
            relocate_tasks(
                session,
                repository,
                [_mapping(task, area)],
                journal_dir=tmp_path / "journals",
                apply=True,
                backup_dir=backup_dir,
                backup_evidence=evidence,
            )
    assert not backup_dir.exists()
    assert not (tmp_path / "journals").exists()

    evidence = _backup_evidence(tmp_path, repository)
    with factory() as session:
        result = relocate_tasks(
            session,
            repository,
            [_mapping(task, area)],
            journal_dir=tmp_path / "journals",
            apply=True,
            backup_dir=backup_dir,
            backup_evidence=evidence,
        )
    assert result["relocated"] == [task.record_id]


def test_apply_rejects_forged_regular_backup_artifacts_before_any_mutation(tmp_path: Path) -> None:
    repository, project, area, task = _records(tmp_path)
    factory = _session_factory(tmp_path)
    journal_dir = tmp_path / "journals"
    backup_dir = tmp_path / "source-backups"

    with factory() as session:
        with pytest.raises(RelocationError, match="wiki backup"):
            relocate_tasks(
                session,
                repository,
                [_mapping(task, area)],
                journal_dir=journal_dir,
                apply=True,
                backup_dir=backup_dir,
                backup_evidence=_forged_backup_evidence(tmp_path, repository),
            )
        assert session.scalar(select(Task).where(Task.wiki_id == task.record_id)) is None

    assert repository.read(task.path).fields["owner_type"] == project.record_type
    assert repository.read(task.path).fields["owner_wiki_id"] == project.record_id
    assert not (repository.root / repository.task_path(area, task.title, task.record_id)).exists()
    assert not journal_dir.exists()
    assert not backup_dir.exists()


def test_apply_rejects_backup_evidence_for_a_different_database_or_wiki_snapshot(tmp_path: Path) -> None:
    repository, _project, area, task = _records(tmp_path)
    factory = _session_factory(tmp_path)
    backup_dir = tmp_path / "source-backups"
    journal_dir = tmp_path / "journals"

    database_evidence = _backup_evidence(tmp_path, repository, database_target="sqlite:///another.db")
    with factory() as session:
        with pytest.raises(RelocationError, match="database does not match"):
            relocate_tasks(
                session,
                repository,
                [_mapping(task, area)],
                journal_dir=journal_dir,
                apply=True,
                backup_dir=backup_dir,
                backup_evidence=database_evidence,
            )
    assert not journal_dir.exists()
    assert not backup_dir.exists()

    snapshot_evidence = _backup_evidence(tmp_path, repository)
    repository.write("area", "Changed", {"id": "area-changed", "status": "active"})
    with factory() as session:
        with pytest.raises(RelocationError, match="wiki snapshot does not match"):
            relocate_tasks(
                session,
                repository,
                [_mapping(task, area)],
                journal_dir=journal_dir,
                apply=True,
                backup_dir=backup_dir,
                backup_evidence=snapshot_evidence,
            )
    assert not journal_dir.exists()
    assert not backup_dir.exists()


def test_recovery_rejects_forged_regular_backup_artifacts_before_reading_journals(tmp_path: Path) -> None:
    repository, _project, _area, _task = _records(tmp_path)
    factory = _session_factory(tmp_path)
    journal_dir = tmp_path / "journals"
    journal_dir.mkdir()
    (journal_dir / "unfinished.json").write_text(json.dumps({"state": "planned"}), encoding="utf-8")

    with factory() as session:
        with pytest.raises(RelocationError, match="wiki backup"):
            recover_relocations(
                session,
                repository,
                journal_dir=journal_dir,
                backup_evidence=_forged_backup_evidence(tmp_path, repository),
            )


def test_move_rejects_source_changed_after_preflight_without_owner_or_projection_reconciliation(
    tmp_path: Path, monkeypatch
) -> None:
    repository, project, area, task = _records(tmp_path)
    factory = _session_factory(tmp_path)
    original_new_journal = __import__("lifeos.task_relocation", fromlist=["_new_journal"])._new_journal

    def mutate_source(*args, **kwargs):
        source_file = repository.root / task.path
        source_file.write_text(
            source_file.read_text(encoding="utf-8") + "\nchanged after preflight\n", encoding="utf-8"
        )
        return original_new_journal(*args, **kwargs)

    monkeypatch.setattr("lifeos.task_relocation._new_journal", mutate_source)
    with factory() as session:
        with pytest.raises(RelocationError, match="source hash changed"):
            relocate_tasks(
                session,
                repository,
                [_mapping(task, area)],
                journal_dir=tmp_path / "journals",
                apply=True,
                backup_dir=tmp_path / "backups",
                backup_evidence=_backup_evidence(tmp_path, repository),
            )
        assert session.scalar(select(Task).where(Task.wiki_id == task.record_id)) is None

    unchanged = repository.read(task.path)
    assert unchanged.fields["owner_type"] == "project"
    assert unchanged.fields["owner_wiki_id"] == project.record_id
    assert not (repository.root / repository.task_path(area, task.title, task.record_id)).exists()


def test_recovery_rejects_changed_destination_without_owner_or_projection_reconciliation(
    tmp_path: Path, monkeypatch
) -> None:
    repository, _project, area, task = _records(tmp_path)
    factory = _session_factory(tmp_path)
    journal_dir = tmp_path / "journals"
    evidence = _backup_evidence(tmp_path, repository)

    monkeypatch.setattr(
        "lifeos.task_relocation.sync_wiki_projection", lambda *_args: (_ for _ in ()).throw(RuntimeError("stop"))
    )
    with factory() as session:
        with pytest.raises(RuntimeError, match="stop"):
            relocate_tasks(
                session,
                repository,
                [_mapping(task, area)],
                journal_dir=journal_dir,
                apply=True,
                backup_dir=tmp_path / "backups",
                backup_evidence=evidence,
            )

    destination = repository.root / repository.task_path(area, task.title, task.record_id)
    destination.write_text(
        destination.read_text(encoding="utf-8").replace("owner_type: area", "owner_type: project"), encoding="utf-8"
    )
    monkeypatch.setattr("lifeos.task_relocation.sync_wiki_projection", sync_wiki_projection)
    with factory() as session:
        with pytest.raises(RelocationError, match="source hash changed"):
            recover_relocations(session, repository, journal_dir=journal_dir, backup_evidence=evidence)
        assert session.scalar(select(Task).where(Task.wiki_id == task.record_id)) is None

    assert repository.read(destination.relative_to(repository.root).as_posix()).fields["owner_type"] == "project"
