"""Pure, read-only discovery of approved Markdown checkbox task observations."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException

from lifeos.wiki_links import resolve_wiki_link
from lifeos.wiki_store import parse_frontmatter, task_notes

_DEFAULT_ALLOWED_ROOTS = ("01-Projects", "02-Areas", "dailies")
_DEFAULT_EXCLUSIONS = ("03-Research", "04-Archives", "assets", "templates")
_VALID_CHECKBOX = re.compile(r"^(?P<indent> *)- \[(?P<state> |x|X)\] (?P<label>.+)$")
_LIST_CHECKBOX_LIKE = re.compile(r"^ *- \[")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(([^()\s]+)\)")


@dataclass(frozen=True, slots=True)
class CheckboxTaskSnapshot:
    """An immutable, read-only checkbox occurrence and optional safe metadata."""

    source_path: str
    line: int
    column: int
    source_excerpt: str
    checked: bool
    label: str
    content_fingerprint: str
    identity: str
    linked_task_path: str | None
    linked_task_id: str | None
    linked_task_title: str | None
    linked_task_summary: str | None
    linked_task_priority: int | str | None


@dataclass(frozen=True, slots=True)
class CheckboxTaskDiagnostic:
    """An immutable input finding at a checkbox source locator."""

    code: str
    severity: str
    message: str
    source_path: str
    line: int
    column: int
    source_excerpt: str
    link_destination: str | None = None
    linked_record_path: str | None = None


@dataclass(frozen=True, slots=True)
class CheckboxTaskScanResult:
    """Immutable scanner output with the effective default policy made explicit."""

    tasks: tuple[CheckboxTaskSnapshot, ...]
    diagnostics: tuple[CheckboxTaskDiagnostic, ...]
    effective_allowed_roots: tuple[str, ...]
    effective_exclusions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CheckboxTaskScanPolicy:
    """Deployment-provided exclusions reported alongside otherwise fixed defaults."""

    exclusions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _LinkedMetadata:
    path: str
    record_id: str
    title: str | None
    summary: str | None
    priority: int | str | None
    status: str | None


def _diagnostic(
    code: str,
    message: str,
    source_path: str,
    line: int,
    source_excerpt: str,
    *,
    link_destination: str | None = None,
    linked_record_path: str | None = None,
) -> CheckboxTaskDiagnostic:
    return CheckboxTaskDiagnostic(
        code=code,
        severity="warning",
        message=message,
        source_path=source_path,
        line=line,
        column=source_excerpt.index("-") + 1,
        source_excerpt=source_excerpt,
        link_destination=link_destination,
        linked_record_path=linked_record_path,
    )


def _is_discoverable(path: Path, root: Path, allowed_roots: tuple[str, ...], exclusions: tuple[str, ...]) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    if not relative.parts or relative.parts[0] not in allowed_roots:
        return False
    return not any(part.startswith(".") or part in exclusions for part in relative.parts)


def _markdown_files(root: Path, allowed_roots: tuple[str, ...], exclusions: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for allowed_root in allowed_roots:
        directory = root / allowed_root
        if directory.is_symlink() or not directory.is_dir():
            continue
        for path in directory.rglob("*.md"):
            if path.is_symlink() or not path.is_file() or not _is_discoverable(path, root, allowed_roots, exclusions):
                continue
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _link_destination(label: str) -> tuple[str, str] | None:
    links = _MARKDOWN_LINK.findall(label)
    if len(links) != 1:
        return None
    return links[0]


def _is_safe_link_destination(destination: str) -> bool:
    parsed = urlparse(destination)
    return not (
        destination.startswith("/")
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or ".." in Path(destination).parts
        or Path(destination).suffix.casefold() != ".md"
    )


def _linked_metadata(root: Path, source: Path, destination: str) -> tuple[_LinkedMetadata | None, str | None]:
    if not _is_safe_link_destination(destination):
        return None, "UNSAFE_TASK_LINK"
    raw_target = source.parent / destination
    try:
        raw_target_path = raw_target.relative_to(root).as_posix()
    except ValueError:
        return None, "UNSAFE_TASK_LINK"
    try:
        link = resolve_wiki_link(raw_target_path, root)
    except HTTPException:
        return None, "UNSAFE_TASK_LINK"
    if not link["available"]:
        return None, "MISSING_TASK_RECORD" if link["link_status"] == "missing" else "UNSAFE_TASK_LINK"
    resolved_target = raw_target.resolve()
    target_path = str(link["path"])
    try:
        text = resolved_target.read_text(encoding="utf-8")
        fields, body = parse_frontmatter(text)
    except (OSError, UnicodeDecodeError, ValueError):
        return None, "UNTYPED_TASK_RECORD"
    record_type = fields.get("type")
    record_id = fields.get("id")
    if record_type != "task":
        return None, "WRONG_TASK_RECORD_TYPE" if record_type else "UNTYPED_TASK_RECORD"
    if not isinstance(record_id, str) or not record_id.strip():
        return None, "UNTYPED_TASK_RECORD"
    title = fields.get("title")
    title_value = title if isinstance(title, str) else None
    priority = fields.get("priority")
    priority_value = priority if isinstance(priority, (int, str)) and not isinstance(priority, bool) else None
    status = fields.get("status")
    status_value = status if isinstance(status, str) else None
    # ``task_notes`` needs only a WikiRecord-shaped value; avoid repository reads/writes.
    from lifeos.wiki_store import WikiRecord

    record = WikiRecord("task", record_id, title_value or resolved_target.stem, target_path, fields, body, "")
    return _LinkedMetadata(target_path, record_id, title_value, task_notes(record), priority_value, status_value), None


def _link_diagnostic_message(code: str) -> str:
    return {
        "UNSAFE_TASK_LINK": "Task-record link is unsafe and was not read.",
        "MISSING_TASK_RECORD": "Linked task record is missing.",
        "UNTYPED_TASK_RECORD": "Linked Markdown record is not a usable typed task.",
        "WRONG_TASK_RECORD_TYPE": "Linked typed record is not a task.",
    }[code]


def scan_checkbox_tasks(
    wiki_root: str | Path, *, policy: CheckboxTaskScanPolicy | None = None
) -> CheckboxTaskScanResult:
    """Scan allowed Markdown roots without creating, mutating, or persisting anything."""
    root = Path(wiki_root).resolve()
    configured_policy = policy or CheckboxTaskScanPolicy()
    effective_exclusions = tuple(dict.fromkeys((*_DEFAULT_EXCLUSIONS, *configured_policy.exclusions)))
    tasks: list[CheckboxTaskSnapshot] = []
    diagnostics: list[CheckboxTaskDiagnostic] = []

    for source in _markdown_files(root, _DEFAULT_ALLOWED_ROOTS, effective_exclusions):
        source_path = source.relative_to(root).as_posix()
        try:
            lines = source.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, source_excerpt in enumerate(lines, start=1):
            match = _VALID_CHECKBOX.match(source_excerpt)
            if match is None:
                if _LIST_CHECKBOX_LIKE.match(source_excerpt):
                    diagnostics.append(
                        _diagnostic(
                            "MALFORMED_CHECKBOX",
                            "Checklist item does not use the supported checkbox grammar.",
                            source_path,
                            line_number,
                            source_excerpt,
                        )
                    )
                continue

            label = match.group("label")
            link_destination: str | None = None
            linked: _LinkedMetadata | None = None
            link_match = _link_destination(label)
            if link_match is not None:
                link_label, link_destination = link_match
                label = link_label
                linked, link_code = _linked_metadata(root, source, link_destination)
                if link_code is not None:
                    diagnostics.append(
                        _diagnostic(
                            link_code,
                            _link_diagnostic_message(link_code),
                            source_path,
                            line_number,
                            source_excerpt,
                            link_destination=link_destination if link_code != "UNSAFE_TASK_LINK" else None,
                        )
                    )

            fingerprint = hashlib.sha256(f"{source_path}\0{source_excerpt}".encode("utf-8")).hexdigest()
            identity = (
                f"{linked.record_id} plus checkbox occurrence locator"
                if linked is not None
                else "plain source-path plus content-fingerprint; read-only"
            )
            tasks.append(
                CheckboxTaskSnapshot(
                    source_path=source_path,
                    line=line_number,
                    column=source_excerpt.index("-") + 1,
                    source_excerpt=source_excerpt,
                    checked=match.group("state").casefold() == "x",
                    label=label,
                    content_fingerprint=fingerprint,
                    identity=identity,
                    linked_task_path=linked.path if linked else None,
                    linked_task_id=linked.record_id if linked else None,
                    linked_task_title=linked.title if linked else None,
                    linked_task_summary=linked.summary if linked else None,
                    linked_task_priority=linked.priority if linked else None,
                )
            )
            if linked is not None and (
                (match.group("state") == " " and linked.status == "completed")
                or (match.group("state").casefold() == "x" and linked.status == "open")
            ):
                checkbox_state = "completed" if match.group("state").casefold() == "x" else "open"
                diagnostics.append(
                    _diagnostic(
                        "CHECKBOX_STATUS_DISAGREEMENT",
                        f"Checkbox is {checkbox_state} but linked task record status is {linked.status}; "
                        "checkbox state remains authoritative.",
                        source_path,
                        line_number,
                        source_excerpt,
                        link_destination=link_destination,
                        linked_record_path=linked.path,
                    )
                )

    linked_occurrences: dict[str, list[CheckboxTaskSnapshot]] = {}
    for task in tasks:
        if task.linked_task_id is not None:
            linked_occurrences.setdefault(task.linked_task_id, []).append(task)
    for occurrences in linked_occurrences.values():
        if len(occurrences) > 1:
            for task in occurrences:
                diagnostics.append(
                    _diagnostic(
                        "DUPLICATE_LINKED_TASK_RECORD",
                        "Linked task record is referenced by multiple checkbox occurrences.",
                        task.source_path,
                        task.line,
                        task.source_excerpt,
                        linked_record_path=task.linked_task_path,
                    )
                )

    return CheckboxTaskScanResult(
        tasks=tuple(sorted(tasks, key=lambda task: (task.source_path, task.line))),
        diagnostics=tuple(
            sorted(diagnostics, key=lambda diagnostic: (diagnostic.source_path, diagnostic.line, diagnostic.code))
        ),
        effective_allowed_roots=_DEFAULT_ALLOWED_ROOTS,
        effective_exclusions=effective_exclusions,
    )
