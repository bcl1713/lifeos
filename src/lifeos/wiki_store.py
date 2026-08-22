"""Structured, human-readable wiki persistence for LifeOS domain records."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError

_TYPED_PREFIX = {"project": "prj", "area": "area", "goal": "goal", "routine": "rtn", "task": "tsk"}


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.default_flow_style = False
    yaml.width = 4096
    return yaml


def _normalize_yaml_scalars(value: Any) -> Any:
    if isinstance(value, str) and any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        value = value.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        for key in list(value):
            value[key] = _normalize_yaml_scalars(value[key])
    elif isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _normalize_yaml_scalars(item)
    return value


def _repair_legacy_plain_scalars(frontmatter: str) -> str:
    repaired: list[str] = []
    for line in frontmatter.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        newline = line[len(content) :]
        if content and not content[0].isspace() and ":" in content:
            key, raw = content.split(":", 1)
            value = raw.lstrip()
            if ": " in value and not value.startswith(('"', "'", "[", "{", "|", ">")):
                content = f"{key}: {json.dumps(value)}"
        repaired.append(content + newline)
    return "".join(repaired)


class WikiConflictError(ValueError):
    """Raised when a portal write would overwrite a newer wiki version."""


class WikiReconciliationRequiredError(RuntimeError):
    """Raised when canonical source changed but its projection transaction failed."""

    def __init__(self, message: str, *, wiki_id: str, wiki_path: str):
        super().__init__(message)
        self.wiki_id = wiki_id
        self.wiki_path = wiki_path


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "untitled"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError("unterminated frontmatter")
    frontmatter = text[4 : end + 1]
    try:
        loaded = _yaml().load(frontmatter)
    except YAMLError:
        loaded = _yaml().load(_repair_legacy_plain_scalars(frontmatter))
    if loaded is None:
        values: dict[str, Any] = CommentedMap()
    elif not isinstance(loaded, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    else:
        values = _normalize_yaml_scalars(loaded)
    return values, text[end + 4 :].lstrip("\n")


def render_frontmatter(values: dict[str, Any], body: str) -> str:
    stream = io.StringIO()
    _yaml().dump(values, stream)
    return f"---\n{stream.getvalue()}---\n\n{body.rstrip()}\n"


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

    def task_path(self, owner: WikiRecord | None, title: str, record_id: str) -> str:
        if owner is None:
            target = self.root / "00-Inbox" / "tasks" / f"{slugify(title)}-{record_id}.md"
        else:
            if owner.record_type not in {"project", "area"}:
                raise ValueError("task owner must be a project or area")
            target = (self.root / owner.path).parent / "tasks" / f"{slugify(title)}-{record_id}.md"
        return target.relative_to(self.root).as_posix()

    def _atomic_write(self, target: Path, text: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        existing_stat = target.stat() if target.exists() else None
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            if existing_stat is None:
                temporary.chmod(0o664)
                temporary.replace(target)
            else:
                with target.open("w", encoding="utf-8") as handle:
                    handle.write(temporary.read_text(encoding="utf-8"))
                    handle.flush()
                    os.fsync(handle.fileno())
        finally:
            temporary.unlink(missing_ok=True)

    def _register_in_index(self, record_type: str, record: "WikiRecord") -> None:
        category = {"project": "01-Projects", "area": "02-Areas"}.get(record_type)
        if category is None:
            return
        index = self.root / category / "index.md"
        target = record.path.removesuffix(".md")
        link = f"[[{target}|{record.title}]]"
        if index.exists():
            text = index.read_text(encoding="utf-8")
            if link in text:
                return
        else:
            text = f"# {'Projects' if record_type == 'project' else 'Areas'}\n"
        self._atomic_write(index, text.rstrip() + f"\n\n- {link}\n")

    def _indexed_paths(self, record_type: str) -> list[Path]:
        category = {"project": "01-Projects", "area": "02-Areas"}[record_type]
        index = self.root / category / "index.md"
        if not index.is_file():
            return []
        paths: list[Path] = []
        for raw in re.findall(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]", index.read_text(encoding="utf-8")):
            candidate = (self.root / raw.strip()).resolve()
            try:
                candidate.relative_to(self.root)
            except ValueError:
                continue
            options = [candidate]
            if candidate.suffix.casefold() != ".md":
                options.extend([candidate.with_suffix(".md"), candidate / "index.md", candidate / "Index.md"])
                parent = candidate.parent
                if parent.is_dir():
                    expected_names = {f"{candidate.name}.md".casefold(), candidate.name.casefold()}
                    options.extend(
                        path for path in parent.iterdir() if path.is_file() and path.name.casefold() in expected_names
                    )
            match = next((option for option in options if option.is_file()), None)
            if match is not None and match not in paths:
                paths.append(match)
        return paths

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
        selected_path = path or (existing.path if existing else None)
        if selected_path is None:
            candidate = self._path(record_type, title, record_id=record_id)
            if candidate.exists() and record_type in {"project", "area"}:
                candidate_record = self.read(candidate.relative_to(self.root).as_posix())
                if candidate_record.record_id != record_id:
                    category = "01-Projects" if record_type == "project" else "02-Areas"
                    candidate = self.root / category / f"{slugify(title)}-{slugify(record_id)}" / "index.md"
            selected_path = candidate.relative_to(self.root).as_posix()
        target = (self.root / selected_path).resolve()
        target.relative_to(self.root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if expected_hash is not None:
            if not target.exists():
                raise WikiConflictError("Canonical wiki record disappeared")
            actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                raise WikiConflictError("Canonical wiki record changed since it was read")
        existing_fields: dict[str, Any] = CommentedMap()
        if target.exists():
            existing_fields, existing_body = parse_frontmatter(target.read_text(encoding="utf-8"))
            if not body:
                body = existing_body
        values = existing_fields
        values.update({"schema_version": "1", "id": record_id, "type": record_type, "title": title})
        values.update(fields)
        values["updated"] = datetime.now(timezone.utc).date().isoformat()
        if not body:
            body = f"# {title}\n\n## Summary\n\n"
        self._atomic_write(target, render_frontmatter(values, body))
        text = target.read_text(encoding="utf-8")
        record = WikiRecord(record_type, record_id, title, target.relative_to(self.root).as_posix(), values, body, hashlib.sha256(text.encode()).hexdigest())
        self._register_in_index(record_type, record)
        return record

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
        category_indexes = {
            (self.root / "01-Projects" / "index.md").resolve(),
            (self.root / "02-Areas" / "index.md").resolve(),
        }
        if record_type in {"project", "area"}:
            paths = self._indexed_paths(record_type) + [
                path
                for path in (self.root / "04-Archives").rglob("*.md")
                if "templates" not in path.relative_to(self.root).parts
            ]
        elif record_type is None:
            paths = self._indexed_paths("project") + self._indexed_paths("area")
            paths += [
                path
                for path in self.root.rglob("*.md")
                if "templates" not in path.relative_to(self.root).parts
                and path.resolve() not in category_indexes
            ]
        else:
            paths = [
                path
                for path in self.root.rglob("*.md")
                if "templates" not in path.relative_to(self.root).parts
                and path.resolve() not in category_indexes
            ]
        seen: set[str] = set()
        seen_files: set[tuple[int, int]] = set()
        for path in paths:
            try:
                stat = path.stat()
                physical_identity = (stat.st_dev, stat.st_ino)
                if physical_identity in seen_files:
                    continue
                record = self.read(path.relative_to(self.root).as_posix())
            except (OSError, ValueError):
                continue
            if not record.record_id and record.record_type in {"project", "area"}:
                record = WikiRecord(
                    record.record_type,
                    f"{_TYPED_PREFIX[record.record_type]}-{slugify(record.title)}",
                    record.title,
                    record.path,
                    record.fields,
                    record.body,
                    record.content_hash,
                )
            if (
                record.record_type in _TYPED_PREFIX
                and record.record_id
                and "{{" not in record.record_id
                and (record_type is None or record.record_type == record_type)
                and record.path not in seen
            ):
                records.append(record)
                seen.add(record.path)
                seen_files.add(physical_identity)
        return sorted(records, key=lambda item: (item.record_type, item.title.lower()))

    def authoritative_records(self) -> list[WikiRecord]:
        """Choose one canonical record per ID, preferring active sources to archives."""
        records_by_id: dict[str, list[WikiRecord]] = {}
        for record in self.list_records():
            records_by_id.setdefault(record.record_id, []).append(record)

        authoritative: list[WikiRecord] = []
        conflicts: dict[str, list[str]] = {}
        for record_id, candidates in records_by_id.items():
            record_types = {candidate.record_type for candidate in candidates}
            selected_precedence = max(0 if candidate.path.startswith("04-Archives/") else 1 for candidate in candidates)
            selected = [
                candidate
                for candidate in candidates
                if (0 if candidate.path.startswith("04-Archives/") else 1) == selected_precedence
            ]
            if len(record_types) != 1 or len(selected) != 1:
                conflicts[record_id] = sorted(candidate.path for candidate in candidates)
                continue
            authoritative.append(selected[0])

        if conflicts:
            detail = "; ".join(
                f"{record_id}: {', '.join(paths)}" for record_id, paths in sorted(conflicts.items())
            )
            raise ValueError(f"ambiguous canonical wiki IDs: {detail}")
        return sorted(authoritative, key=lambda item: (item.record_type, item.title.lower()))

    def find_by_id(self, record_id: str) -> WikiRecord | None:
        return next((record for record in self.authoritative_records() if record.record_id == record_id), None)

    def find_by_title(self, record_type: str, title: str) -> WikiRecord | None:
        return next(
            (
                record
                for record in self.authoritative_records()
                if record.record_type == record_type and record.title.casefold() == title.casefold()
            ),
            None,
        )
