"""Structured, human-readable wiki persistence for LifeOS domain records."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_TYPED_PREFIX = {"project": "prj", "area": "area", "goal": "goal", "routine": "rtn", "task": "tsk"}


class WikiConflictError(ValueError):
    """Raised when a portal write would overwrite a newer wiki version."""


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "untitled"


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError("unterminated frontmatter")
    values: dict[str, Any] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, raw = line.split(":", 1)
        raw = raw.strip()
        if raw.startswith("[") or raw.startswith("{"):
            try:
                values[key.strip()] = json.loads(raw)
                continue
            except json.JSONDecodeError:
                if raw.startswith("[") and raw.endswith("]"):
                    values[key.strip()] = [part.strip().strip("\"'") for part in raw[1:-1].split(",") if part.strip()]
                    continue
        values[key.strip()] = raw.strip('"\'')
    return values, text[end + 4 :].lstrip("\n")


def render_frontmatter(values: dict[str, Any], body: str) -> str:
    lines = ["---"]
    for key, value in values.items():
        rendered = _scalar(value)
        if isinstance(value, (list, dict)):
            lines.append(f"{key}: {rendered}")
        elif re.fullmatch(r"[A-Za-z0-9_./:@+ -]*", rendered):
            lines.append(f"{key}: {rendered}")
        else:
            lines.append(f"{key}: {json.dumps(rendered)}")
    lines.extend(["---", "", body.rstrip(), ""])
    return "\n".join(lines)


@dataclass(frozen=True)
class WikiRecord:
    record_type: str
    record_id: str
    title: str
    path: str
    fields: dict[str, Any]
    body: str
    content_hash: str


class WikiRepository:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _path(self, record_type: str, title: str, *, parent: str | None = None, record_id: str | None = None) -> Path:
        if record_type == "project":
            return self.root / "01-Projects" / slugify(title) / "index.md"
        if record_type == "area":
            return self.root / "02-Areas" / slugify(title) / "index.md"
        base = self.root / (parent or "01-Projects/LifeOS") / "lifeos" / f"{record_type}s"
        return base / f"{slugify(title)}-{record_id or slugify(title)}.md"

    def write(
        self,
        record_type: str,
        title: str,
        fields: dict[str, Any],
        body: str = "",
        *,
        path: str | None = None,
        expected_hash: str | None = None,
    ) -> WikiRecord:
        if record_type not in _TYPED_PREFIX:
            raise ValueError(f"unsupported wiki record type: {record_type}")
        record_id = str(fields.get("id") or f"{_TYPED_PREFIX[record_type]}-{slugify(title)}")
        existing = self.find_by_id(record_id) if record_id else None
        if existing is None and path is None:
            existing = next((item for item in self.list_records(record_type) if item.title.casefold() == title.casefold()), None)
        target = (self.root / (path or (existing.path if existing else self._path(record_type, title, record_id=record_id)))).resolve()
        target.relative_to(self.root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if expected_hash is not None:
            if not target.exists():
                raise WikiConflictError("Canonical wiki record disappeared")
            actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                raise WikiConflictError("Canonical wiki record changed since it was read")
        if target.exists() and not body:
            _, body = parse_frontmatter(target.read_text(encoding="utf-8"))
        values = {"schema_version": "1", "id": record_id, "type": record_type, "title": title, **fields}
        values["updated"] = datetime.now(timezone.utc).date().isoformat()
        if not body:
            body = f"# {title}\n\n## Summary\n\n"
        target.write_text(render_frontmatter(values, body), encoding="utf-8")
        text = target.read_text(encoding="utf-8")
        return WikiRecord(record_type, record_id, title, target.relative_to(self.root).as_posix(), values, body, hashlib.sha256(text.encode()).hexdigest())

    def read(self, path: str) -> WikiRecord:
        target = (self.root / path).resolve()
        target.relative_to(self.root)
        text = target.read_text(encoding="utf-8")
        fields, body = parse_frontmatter(text)
        record_type = str(fields.get("type", "unknown"))
        if record_type == "unknown" and target.name.casefold() == "index.md":
            parts = target.relative_to(self.root).parts
            if parts and parts[0] == "01-Projects":
                record_type = "project"
            elif parts and parts[0] == "02-Areas":
                record_type = "area"
        title = str(fields.get("title") or next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), target.stem))
        return WikiRecord(record_type, str(fields.get("id", "")), title, target.relative_to(self.root).as_posix(), fields, body, hashlib.sha256(text.encode()).hexdigest())

    def list_records(self, record_type: str | None = None) -> list[WikiRecord]:
        records: list[WikiRecord] = []
        for path in self.root.rglob("*.md"):
            try:
                record = self.read(path.relative_to(self.root).as_posix())
            except (OSError, ValueError):
                continue
            if record.record_type in _TYPED_PREFIX and (record_type is None or record.record_type == record_type):
                records.append(record)
        return sorted(records, key=lambda item: (item.record_type, item.title.lower()))

    def find_by_id(self, record_id: str) -> WikiRecord | None:
        return next((record for record in self.list_records() if record.record_id == record_id), None)

    def find_by_title(self, record_type: str, title: str) -> WikiRecord | None:
        return next((record for record in self.list_records() if record.record_type == record_type and record.title.casefold() == title.casefold()), None)
