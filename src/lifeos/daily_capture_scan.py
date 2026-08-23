"""Scan explicitly marked daily captures into review-only promotion proposals."""
from __future__ import annotations

import hashlib
import os
import re
import stat
from datetime import date
from pathlib import Path
from typing import Any

from lifeos.wiki_store import WikiRecord, WikiRepository

_CAPTURE_LINE = re.compile(r"^- \[ \] \[lifeos-capture (?P<attributes>[^\]]+)\] (?P<title>\S(?:.*\S)?)$")
_ATTRIBUTE = re.compile(r"(?P<key>id|target|due|priority)=(?P<value>[^\s=]+)")
_CAPTURE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,127}$")
_TARGET = re.compile(r"^(?P<type>project|area):(?P<id>[A-Za-z][A-Za-z0-9_-]{2,127})$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PRIORITY = re.compile(r"^[0-3]$")


def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _daily_directory(repository: WikiRepository, daily_root: str | Path) -> Path:
    root = Path(daily_root)
    if root.is_absolute() or root in {Path(""), Path(".")} or ".." in root.parts:
        raise ValueError("daily root must be relative to the canonical wiki root")
    candidate = repository.root
    for part in root.parts:
        candidate /= part
        if candidate.is_symlink():
            raise ValueError("daily root must be a non-symlink directory")
    directory = candidate.resolve()
    try:
        directory.relative_to(repository.root)
    except ValueError as exc:
        raise ValueError("daily root escapes the canonical wiki root") from exc
    return directory


def _exception(capture_id: str | None, path: str, line: int, code: str, detail: str) -> dict[str, Any]:
    return {
        "capture_id": capture_id,
        "source_path": path,
        "source_line": line,
        "code": code,
        "detail": detail,
    }


def _capture_attributes(value: str) -> dict[str, str] | None:
    attributes: dict[str, str] = {}
    position = 0
    for match in _ATTRIBUTE.finditer(value):
        if match.start() != position or (position and value[position - 1] != " "):
            return None
        key, item = match.group("key"), match.group("value")
        if key in attributes:
            return None
        attributes[key] = item
        position = match.end()
        if position < len(value):
            if value[position] != " ":
                return None
            position += 1
    return attributes if position == len(value) else None


def _target(records: dict[str, WikiRecord], value: str) -> tuple[dict[str, str | None] | None, str | None]:
    if value == "inbox":
        return {"type": "inbox", "id": None, "path": "00-Inbox"}, None
    match = _TARGET.fullmatch(value)
    if match is None:
        return None, "target must be inbox, project:<stable-id>, or area:<stable-id>"
    record = records.get(match.group("id"))
    if record is None or record.record_type != match.group("type"):
        return None, "target does not resolve to the declared canonical Project or Area"
    if str(record.fields.get("status") or "active") != "active":
        return None, "target is not active"
    return {"type": record.record_type, "id": record.record_id, "path": record.path}, None


def _promoted_tasks(records: list[WikiRecord]) -> dict[str, list[WikiRecord]]:
    promoted: dict[str, list[WikiRecord]] = {}
    for record in records:
        if record.record_type != "task":
            continue
        capture_id = record.fields.get("daily_capture_id")
        if isinstance(capture_id, str) and capture_id:
            promoted.setdefault(capture_id, []).append(record)
    return promoted


def _read_daily_note(path: Path, repository: WikiRepository) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = Path(f"/proc/self/fd/{descriptor}").resolve()
        opened.relative_to(repository.root)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("daily note must be a regular file inside the canonical wiki root")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            return handle.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def scan_daily_captures(
    repository: WikiRepository, *, daily_root: str | Path, start: str | date, end: str | date
) -> dict[str, list[dict[str, Any]]]:
    """Read date-named Markdown notes and return deterministic proposals without writes.

    Only a line using the exact opt-in grammar is eligible:
    ``- [ ] [lifeos-capture id=<id> target=<target> [due=YYYY-MM-DD] [priority=0..3]] <title>``.
    """
    start_date, end_date = _parse_date(start), _parse_date(end)
    if end_date < start_date:
        raise ValueError("end date must not precede start date")
    directory = _daily_directory(repository, daily_root)
    if not directory.exists():
        return {"proposals": [], "exceptions": []}
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("daily root must be a non-symlink directory")

    try:
        records = repository.authoritative_records()
    except ValueError as exc:
        return {
            "proposals": [],
            "exceptions": [
                _exception(None, "__canonical__", 0, "canonical_authority_conflict", str(exc)),
            ],
        }
    records_by_id = {record.record_id: record for record in records}
    promoted = _promoted_tasks(records)
    duplicate_promotions = {capture_id: items for capture_id, items in promoted.items() if len(items) > 1}
    if duplicate_promotions:
        detail = "; ".join(
            f"{capture_id}: {', '.join(sorted(item.path for item in items))}"
            for capture_id, items in sorted(duplicate_promotions.items())
        )
        return {
            "proposals": [],
            "exceptions": [
                _exception(None, "__canonical__", 0, "duplicate_promoted_capture_id", detail),
            ],
        }
    candidates: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    capture_occurrences: dict[str, list[tuple[str, int]]] = {}
    files: list[tuple[date, Path]] = []
    for path in directory.rglob("*.md"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            note_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if start_date <= note_date <= end_date:
            files.append((note_date, path))

    for _note_date, path in sorted(files, key=lambda item: item[1].relative_to(repository.root).as_posix()):
        relative = path.relative_to(repository.root).as_posix()
        for number, raw in enumerate(_read_daily_note(path, repository).splitlines(), start=1):
            if not raw.startswith("- [ ] [lifeos-capture "):
                continue
            match = _CAPTURE_LINE.fullmatch(raw)
            if match is None:
                exceptions.append(
                    _exception(
                        None,
                        relative,
                        number,
                        "malformed_capture",
                        "capture marker must use the exact opt-in grammar",
                    )
                )
                continue
            attributes = _capture_attributes(match.group("attributes"))
            if (
                attributes is None
                or set(attributes) - {"id", "target", "due", "priority"}
                or {"id", "target"} - set(attributes)
            ):
                exceptions.append(
                    _exception(None, relative, number, "malformed_capture", "capture attributes are invalid")
                )
                continue
            capture_id = attributes["id"]
            if _CAPTURE_ID.fullmatch(capture_id) is None:
                exceptions.append(
                    _exception(capture_id, relative, number, "malformed_capture", "capture id is invalid")
                )
                continue
            capture_occurrences.setdefault(capture_id, []).append((relative, number))
            due = attributes.get("due")
            if due is not None:
                if _ISO_DATE.fullmatch(due) is None:
                    exceptions.append(
                        _exception(capture_id, relative, number, "malformed_capture", "due must be YYYY-MM-DD")
                    )
                    continue
                try:
                    date.fromisoformat(due)
                except ValueError:
                    exceptions.append(
                        _exception(capture_id, relative, number, "malformed_capture", "due must be YYYY-MM-DD")
                    )
                    continue
            priority: int | None = None
            if "priority" in attributes:
                if _PRIORITY.fullmatch(attributes["priority"]) is None:
                    exceptions.append(
                        _exception(capture_id, relative, number, "malformed_capture", "priority must be 0, 1, 2, or 3")
                    )
                    continue
                priority = int(attributes["priority"])
            target, problem = _target(records_by_id, attributes["target"])
            if problem is not None:
                code = (
                    "stale_target"
                    if attributes["target"] == "inbox" or _TARGET.fullmatch(attributes["target"])
                    else "invalid_target"
                )
                exceptions.append(_exception(capture_id, relative, number, code, problem))
                continue
            candidates.append(
                {
                    "capture_id": capture_id,
                    "source_path": relative,
                    "source_line": number,
                    "source_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                    "title": match.group("title"),
                    "target": target,
                    "due": due,
                    "priority": priority,
                }
            )

    duplicate_capture_ids = {capture_id for capture_id, items in capture_occurrences.items() if len(items) > 1}
    for capture_id in sorted(duplicate_capture_ids):
        for path, line in capture_occurrences[capture_id]:
            exceptions.append(
                _exception(
                    capture_id,
                    path,
                    line,
                    "duplicate_capture_id",
                    "capture id appears more than once in the scan window",
                )
            )
    proposals: list[dict[str, Any]] = []
    for candidate in candidates:
        capture_id = candidate["capture_id"]
        if capture_id in duplicate_capture_ids:
            continue
        existing = promoted.get(capture_id)
        if existing is not None:
            promoted_task = existing[0]
            if promoted_task.fields.get("daily_capture_source_hash") == candidate["source_hash"]:
                code, detail = "already_promoted", "capture id already has a canonical task with this source hash"
            else:
                code, detail = "source_changed", "capture id already has a canonical task but its source hash changed"
            exceptions.append(_exception(capture_id, candidate["source_path"], candidate["source_line"], code, detail))
            continue
        proposals.append(candidate)

    return {
        "proposals": sorted(proposals, key=lambda item: (item["source_path"], item["source_line"], item["capture_id"])),
        "exceptions": sorted(
            exceptions,
            key=lambda item: (item["source_path"], item["source_line"], item["capture_id"] or "", item["code"]),
        ),
    }
