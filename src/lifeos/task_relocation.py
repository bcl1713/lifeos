"""Dry-run inventory and controlled canonical task relocation workflow."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from lifeos.scripts_bridge import sync_wiki_projection
from lifeos.wiki_store import WikiRecord, WikiRepository, render_frontmatter


class RelocationError(ValueError):
    """Raised when a controlled task relocation cannot pass preflight."""


_MAPPING_FIELDS = {"source_id", "source_path", "source_hash", "owner_type", "owner_wiki_id", "owner_path"}
_RELATIONSHIP_FIELDS = ("goal_wiki_id", "project_wiki_id", "routine_wiki_id", "parent_wiki_id", "depends_on")


def _active_task_records(repository: WikiRepository) -> list[WikiRecord]:
    records = [record for record in repository.list_records("task") if not record.path.startswith("04-Archives/")]
    by_id: dict[str, list[WikiRecord]] = {}
    for record in records:
        by_id.setdefault(record.record_id, []).append(record)
    duplicates = {
        record_id: sorted(item.path for item in grouped) for record_id, grouped in by_id.items() if len(grouped) > 1
    }
    if duplicates:
        detail = "; ".join(f"{record_id}: {', '.join(paths)}" for record_id, paths in sorted(duplicates.items()))
        raise RelocationError(f"duplicate active canonical task IDs: {detail}")
    return sorted(records, key=lambda record: record.record_id)


def _owner(repository: WikiRepository, owner_type: Any, owner_wiki_id: Any) -> WikiRecord | None:
    if owner_type not in {"project", "area"} or not isinstance(owner_wiki_id, str) or not owner_wiki_id:
        return None
    owner = repository.find_by_id(owner_wiki_id)
    return owner if owner is not None and owner.record_type == owner_type else None


def _task_state(repository: WikiRepository, record: WikiRecord) -> dict[str, Any]:
    owner_type = record.fields.get("owner_type")
    owner_wiki_id = record.fields.get("owner_wiki_id")
    owner = _owner(repository, owner_type, owner_wiki_id)
    target_path = repository.task_path(owner, record.title, record.record_id) if owner is not None else None
    candidate = (
        {"owner_type": owner.record_type, "owner_wiki_id": owner.record_id, "owner_path": owner.path} if owner else None
    )
    issues: list[str] = []
    if owner is None:
        issues.append("owner is absent, invalid, or requires explicit mapping")
    elif target_path != record.path:
        issues.append("task path does not match owner target")
    return {
        "id": record.record_id,
        "path": record.path,
        "hash": record.content_hash,
        "owner_type": owner_type,
        "owner_wiki_id": owner_wiki_id,
        "task_list": record.fields.get("task_list"),
        "relationships": {
            field: record.fields.get(field) if field != "depends_on" else record.fields.get(field, [])
            for field in _RELATIONSHIP_FIELDS
        },
        "owner_candidate": candidate,
        "target_path": target_path,
        "issues": issues,
    }


def inventory_task_ownership(repository: WikiRepository) -> dict[str, Any]:
    """Report canonical task ownership, paths, relationships, and conflicts without writes."""
    tasks = [_task_state(repository, record) for record in _active_task_records(repository)]
    paths: dict[str, list[str]] = {}
    for task in tasks:
        paths.setdefault(str(task["path"]), []).append(str(task["id"]))
    return {
        "tasks": tasks,
        "path_conflicts": {path: ids for path, ids in sorted(paths.items()) if len(ids) > 1},
        "ambiguous_or_unowned": [task["id"] for task in tasks if task["issues"]],
    }


def load_relocation_mappings(path: str | Path) -> list[dict[str, Any]]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    mappings = value.get("mappings") if isinstance(value, dict) else value
    if not isinstance(mappings, list):
        raise RelocationError("mapping file must be a JSON list or an object with a mappings list")
    return [dict(item) for item in mappings if isinstance(item, dict)]


def _validated_operation(repository: WikiRepository, mapping: dict[str, Any]) -> dict[str, Any]:
    has_exact_required_fields = set(mapping) == _MAPPING_FIELDS
    has_string_values = all(isinstance(mapping[key], str) and mapping[key] for key in _MAPPING_FIELDS)
    if not has_exact_required_fields or not has_string_values:
        raise RelocationError(f"mapping must contain exactly: {', '.join(sorted(_MAPPING_FIELDS))}")
    if mapping["owner_type"] not in {"project", "area"}:
        raise RelocationError(
            "mapping owner_type must be project or area; Inbox/unowned tasks require a later explicit policy"
        )
    records = {record.record_id: record for record in _active_task_records(repository)}
    source = records.get(mapping["source_id"])
    if source is None:
        raise RelocationError(f"source ID is missing or is not active: {mapping['source_id']}")
    if source.path != mapping["source_path"]:
        raise RelocationError(f"source path changed for {source.record_id}")
    if source.content_hash != mapping["source_hash"]:
        raise RelocationError(f"source hash changed for {source.record_id}")
    owner = _owner(repository, mapping["owner_type"], mapping["owner_wiki_id"])
    if owner is None:
        raise RelocationError("mapping owner does not resolve to the declared canonical type")
    if owner.path != mapping["owner_path"]:
        raise RelocationError("mapping owner path does not match the stable owner ID")
    destination = repository.task_path(owner, source.title, source.record_id)
    if destination == source.path:
        return {"source": source, "owner": owner, "destination": destination, "unchanged": True}
    destination_file = (repository.root / destination).resolve()
    try:
        destination_file.relative_to(repository.root)
    except ValueError as exc:
        raise RelocationError("destination escapes the wiki root") from exc
    if destination_file.exists() or destination_file.is_symlink():
        raise RelocationError(f"destination already exists: {destination}")
    source_file = repository.root / source.path
    try:
        resolved_source = source_file.resolve(strict=True)
        resolved_source.relative_to(repository.root)
    except (FileNotFoundError, ValueError) as exc:
        raise RelocationError("source escapes the wiki root or disappeared") from exc
    if source_file != resolved_source or source_file.is_symlink() or not source_file.is_file():
        raise RelocationError("source must be a regular canonical file")
    return {"source": source, "owner": owner, "destination": destination, "unchanged": False}


def _journal_path(journal_dir: Path, source: WikiRecord) -> Path:
    digest = hashlib.sha256(f"{source.record_id}\0{source.path}".encode()).hexdigest()[:16]
    return journal_dir / f"{source.record_id}-{digest}.json"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _move_source(operation: dict[str, Any], repository: WikiRepository, journal: dict[str, Any]) -> None:
    source: WikiRecord = operation["source"]
    owner: WikiRecord = operation["owner"]
    source_file = repository.root / source.path
    destination_file = repository.root / operation["destination"]
    destination_file.parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = destination_file.parent.resolve()
    try:
        resolved_parent.relative_to(repository.root)
    except ValueError as exc:
        raise RelocationError("destination parent escapes the wiki root") from exc
    if destination_file.exists() or destination_file.is_symlink():
        raise RelocationError(f"destination already exists: {operation['destination']}")
    journal["state"] = "source_moving"
    os.replace(source_file, destination_file)
    moved = repository.read(operation["destination"])
    _write_relocated_owner(repository, moved, owner)
    read_back = repository.read(operation["destination"])
    if read_back.record_id != source.record_id or read_back.fields.get("owner_wiki_id") != owner.record_id:
        raise RelocationError("destination read-back did not preserve source identity and owner")
    journal["state"] = "source_moved"


def _write_relocated_owner(repository: WikiRepository, record: WikiRecord, owner: WikiRecord) -> None:
    fields = record.fields.copy()
    fields["owner_type"] = owner.record_type
    fields["owner_wiki_id"] = owner.record_id
    fields["updated"] = datetime.now(timezone.utc).date().isoformat()
    repository._atomic_write(repository.root / record.path, render_frontmatter(fields, record.body))


def _new_journal(operation: dict[str, Any], repository: WikiRepository, backup_dir: Path) -> dict[str, Any]:
    source: WikiRecord = operation["source"]
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{source.record_id}-{hashlib.sha256(source.path.encode()).hexdigest()[:16]}.md"
    if backup.exists():
        raise RelocationError(f"backup already exists: {backup}")
    backup.write_bytes((repository.root / source.path).read_bytes())
    return {
        "version": 1,
        "state": "planned",
        "source_id": source.record_id,
        "source_path": source.path,
        "source_hash": source.content_hash,
        "destination_path": operation["destination"],
        "owner_type": operation["owner"].record_type,
        "owner_wiki_id": operation["owner"].record_id,
        "owner_path": operation["owner"].path,
        "backup_path": str(backup),
    }


def _complete_projection(session: Any, repository: WikiRepository, journal: dict[str, Any], journal_path: Path) -> None:
    sync_wiki_projection(session, repository)
    journal["state"] = "complete"
    _write_json(journal_path, journal)


def recover_relocations(session: Any, repository: WikiRepository, *, journal_dir: str | Path) -> list[str]:
    """Reconcile interrupted journaled relocations; completed journals are ignored."""
    directory = Path(journal_dir)
    if not directory.exists():
        return []
    recovered: list[str] = []
    for path in sorted(directory.glob("*.json")):
        journal = json.loads(path.read_text(encoding="utf-8"))
        if journal.get("state") == "complete":
            continue
        destination = repository.root / str(journal["destination_path"])
        source = repository.root / str(journal["source_path"])
        if source.exists():
            raise RelocationError(f"journal {path.name} has not moved its source; rerun with the original mapping")
        if not destination.is_file() or destination.is_symlink():
            raise RelocationError(f"journal {path.name} has neither a safe source nor destination")
        record = repository.read(str(journal["destination_path"]))
        if record.record_id != journal["source_id"]:
            raise RelocationError(f"journal {path.name} destination identity mismatch")
        owner = _owner(repository, journal["owner_type"], journal["owner_wiki_id"])
        if owner is None or owner.path != journal["owner_path"]:
            raise RelocationError(f"journal {path.name} owner no longer resolves by stable ID and path")
        owner_changed = (
            record.fields.get("owner_type") != owner.record_type
            or record.fields.get("owner_wiki_id") != owner.record_id
        )
        if owner_changed:
            _write_relocated_owner(repository, record, owner)
        _complete_projection(session, repository, journal, path)
        recovered.append(record.record_id)
    return recovered


def relocate_tasks(
    session: Any,
    repository: WikiRepository,
    mappings: Iterable[dict[str, Any]],
    *,
    journal_dir: str | Path,
    apply: bool = False,
    backup_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Validate mappings and, only with apply, move each source then refresh its projection."""
    mappings = list(mappings)
    operations = [_validated_operation(repository, mapping) for mapping in mappings]
    unchanged = [operation["source"].record_id for operation in operations if operation["unchanged"]]
    result: dict[str, Any] = {
        "apply": apply,
        "planned": len(operations),
        "unchanged": unchanged,
        "relocated": [],
        "recovered": [],
    }
    if not apply:
        return result
    if backup_dir is None:
        raise RelocationError("--apply requires a verified backup directory")
    directory = Path(journal_dir)
    result["recovered"] = recover_relocations(session, repository, journal_dir=directory)
    for operation in operations:
        if operation["unchanged"]:
            continue
        journal_path = _journal_path(directory, operation["source"])
        if journal_path.exists():
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            if journal.get("state") == "complete":
                result["unchanged"].append(operation["source"].record_id)
                continue
            raise RelocationError(f"unfinished relocation journal: {journal_path}")
        journal = _new_journal(operation, repository, Path(backup_dir))
        _write_json(journal_path, journal)
        _move_source(operation, repository, journal)
        _write_json(journal_path, journal)
        _complete_projection(session, repository, journal, journal_path)
        result["relocated"].append(operation["source"].record_id)
    return result
