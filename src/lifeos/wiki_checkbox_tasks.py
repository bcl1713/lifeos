"""Pure, read-only discovery of approved Markdown checkbox task observations."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import HTTPException

from lifeos.wiki_links import resolve_wiki_link
from lifeos.wiki_store import parse_frontmatter, task_notes

_DEFAULT_ALLOWED_ROOTS = ("01-Projects", "02-Areas", "dailies")
_DEFAULT_EXCLUSIONS = ("03-Research", "04-Archives", "assets", "templates")
_VALID_CHECKBOX = re.compile(r"^(?P<indent> *)- \[(?P<state> |x|X)\] (?P<label>.+)$")
_LIST_CHECKBOX_LIKE = re.compile(r"^ *- \[")
_MARKDOWN_LINK = re.compile(r"(?<!\!)\[([^\]]+)\]\(([^()]+)\)")
_WIKI_LINK = re.compile(r"\[\[([^\[\]]*)\]\]")
_LINK = re.compile(r"(?<!\!)\[([^\]]+)\]\(([^()]+)\)|\[\[([^\[\]]*)\]\]")


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
    supporting_links: tuple["SupportingLink", ...]


@dataclass(frozen=True, slots=True)
class SupportingLink:
    """A literal authored supporting link plus any safe navigation result."""

    label: str
    destination: str
    path: str | None
    fragment: str | None = None
    query: str | None = None
    kind: str = "markdown"
    link_index: int = 0
    target: str | None = None
    anchor: str | None = None
    classification: str = "internal_markdown"
    diagnostic: str | None = None


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
    link_index: int | None = None
    link_kind: str | None = None


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
    link_index: int | None = None,
    link_kind: str | None = None,
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
        link_index=link_index,
        link_kind=link_kind,
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


def _supporting_link(
    root: Path, source: Path, label: str, destination: str
) -> tuple[SupportingLink | None, str | None]:
    parsed = urlparse(destination)
    if parsed.scheme in {"http", "https"}:
        return SupportingLink(label, destination, None, kind="markdown", classification="external"), None
    if not parsed.path or not _is_safe_link_destination(parsed.path) or parsed.scheme or parsed.netloc:
        return SupportingLink(label, destination, None, kind="markdown", classification="unsafe"), "SUPPORTING_LINK_UNSAFE"
    if Path(parsed.path).suffix.casefold() != ".md":
        return SupportingLink(label, destination, None, kind="markdown", classification="non_markdown"), "SUPPORTING_LINK_NON_MARKDOWN"
    raw_target = source.parent / parsed.path
    try:
        raw_target_path = raw_target.relative_to(root).as_posix()
        link = resolve_wiki_link(raw_target_path, root)
    except HTTPException:
        return SupportingLink(label, destination, None, kind="markdown", classification="unsafe"), "SUPPORTING_LINK_UNSAFE"
    if not link["available"]:
        code = "SUPPORTING_LINK_MISSING" if link["link_status"] == "missing" else "SUPPORTING_LINK_UNSAFE"
        return SupportingLink(label, destination, None, kind="markdown", classification="missing" if code.endswith("MISSING") else "unsafe"), code
    return SupportingLink(
        label,
        destination,
        str(link["path"]),
        parsed.fragment or None,
        parsed.query or None,
    ), None


def _wiki_supporting_link(root: Path, source: Path, interior: str) -> tuple[SupportingLink, str | None]:
    target_anchor, sep, display = interior.partition("|")
    target, anchor_sep, anchor = target_anchor.partition("#")
    label = display if sep else target
    invalid = not target or (sep and not display) or any(token in interior for token in ("[[", "]]", "\\"))
    parsed = urlparse(target)
    if invalid or parsed.scheme or parsed.netloc or target.startswith("/"):
        return SupportingLink(label, interior, None, kind="wiki", target=target or None, anchor=anchor or None, classification="malformed"), "SUPPORTING_WIKI_LINK_MALFORMED"
    if ".." in Path(target).parts:
        return SupportingLink(label, interior, None, kind="wiki", target=target, anchor=anchor or None, classification="unsafe"), "SUPPORTING_WIKI_LINK_UNSAFE"
    candidates: list[Path] = []
    for candidate in (root / target, source.parent / target):
        candidate = candidate if candidate.suffix.casefold() == ".md" else candidate.with_suffix(".md")
        if candidate not in candidates:
            candidates.append(candidate)
    available: list[dict[str, str | bool | None]] = []
    unsafe_candidate = False
    for candidate in candidates:
        try:
            relative = candidate.relative_to(root).as_posix()
            link = resolve_wiki_link(relative, root)
        except HTTPException:
            unsafe_candidate = True
            continue
        if link["available"]:
            available.append(link)
        elif link["link_status"] != "missing":
            unsafe_candidate = True
    if not available and len(Path(target).parts) == 1:
        basename = f"{target}.md" if not target.casefold().endswith(".md") else target
        for candidate in root.rglob("*.md"):
            if candidate.name.casefold() == basename.casefold():
                try:
                    link = resolve_wiki_link(candidate.relative_to(root).as_posix(), root)
                except HTTPException:
                    unsafe_candidate = True
                    continue
                if link["available"]:
                    available.append(link)
                elif link["link_status"] != "missing":
                    unsafe_candidate = True
    unique = {str(link["path"]): link for link in available}
    if len(unique) > 1:
        return SupportingLink(label, interior, None, kind="wiki", target=target, anchor=anchor or None, classification="ambiguous"), "SUPPORTING_WIKI_LINK_AMBIGUOUS"
    if not unique and unsafe_candidate:
        return SupportingLink(label, interior, None, kind="wiki", target=target, anchor=anchor or None, classification="unsafe"), "SUPPORTING_WIKI_LINK_UNSAFE"
    if not unique:
        return SupportingLink(label, interior, None, kind="wiki", target=target, anchor=anchor or None, classification="missing"), "SUPPORTING_WIKI_LINK_MISSING"
    path = next(iter(unique))
    return SupportingLink(label, interior, path, kind="wiki", target=target, anchor=anchor or None, classification="internal_wiki"), None


def _link_diagnostic_message(code: str) -> str:
    return {
        "UNSAFE_TASK_LINK": "Task-record link is unsafe and was not read.",
        "MISSING_TASK_RECORD": "Linked task record is missing.",
        "UNTYPED_TASK_RECORD": "Linked Markdown record is not a usable typed task.",
        "WRONG_TASK_RECORD_TYPE": "Linked typed record is not a task.",
        "SUPPORTING_LINK_UNSAFE": "Supporting link is unsafe and was not read.",
        "SUPPORTING_LINK_MISSING": "Supporting link target is missing.",
        "SUPPORTING_LINK_NON_MARKDOWN": "Supporting link target is not Markdown.",
        "LEGACY_TYPED_TASK_LINK": "Legacy unmarked typed-task-shaped link is supporting context only.",
        "TYPED_TASK_LINK_CARDINALITY": "Checkbox has more than one explicit typed-task link.",
        "MALFORMED_TYPED_TASK_LINK": "Explicit typed-task link is malformed.",
        "SUPPORTING_WIKI_LINK_MALFORMED": "Supporting wiki link is malformed or unsafe.",
        "SUPPORTING_WIKI_LINK_UNSAFE": "Supporting wiki link is unsafe and was not read.",
        "SUPPORTING_WIKI_LINK_MISSING": "Supporting wiki link target is missing.",
        "SUPPORTING_WIKI_LINK_AMBIGUOUS": "Supporting wiki link target is ambiguous.",
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
            supporting_links: list[SupportingLink] = []
            parsed_links = list(_LINK.finditer(label))
            typed_matches = [item for item in parsed_links if item.group(2) is not None and item.group(2).startswith("task:")]
            malformed_typed = False
            if len(typed_matches) > 1:
                diagnostics.append(_diagnostic("TYPED_TASK_LINK_CARDINALITY", _link_diagnostic_message("TYPED_TASK_LINK_CARDINALITY"), source_path, line_number, source_excerpt))
            elif len(typed_matches) == 1:
                typed_index = parsed_links.index(typed_matches[0])
                link_destination = typed_matches[0].group(2)
                assert link_destination is not None
                raw_payload = link_destination.removeprefix("task:")
                if (
                    not raw_payload
                    or " " in raw_payload
                    or "#" in raw_payload
                    or "?" in raw_payload
                    or re.search(r"%(?![0-9A-Fa-f]{2})", raw_payload)
                ):
                    malformed_typed = True
                else:
                    decoded_payload = unquote(raw_payload)
                    if " " in decoded_payload or not _is_safe_link_destination(decoded_payload):
                        malformed_typed = True
                    else:
                        linked, link_code = _linked_metadata(root, source, decoded_payload)
                        if link_code is not None:
                            diagnostics.append(_diagnostic(link_code, _link_diagnostic_message(link_code), source_path, line_number, source_excerpt, link_destination=link_destination if link_code != "UNSAFE_TASK_LINK" else None, link_index=typed_index, link_kind="markdown"))
                if malformed_typed:
                    diagnostics.append(_diagnostic("MALFORMED_TYPED_TASK_LINK", _link_diagnostic_message("MALFORMED_TYPED_TASK_LINK"), source_path, line_number, source_excerpt, link_index=typed_index, link_kind="markdown"))

            for link_index, parsed_link in enumerate(parsed_links):
                markdown_destination = parsed_link.group(2)
                if markdown_destination is not None:
                    supporting_label = parsed_link.group(1)
                    assert supporting_label is not None
                    if markdown_destination.startswith("task:"):
                        continue
                    supporting, link_code = _supporting_link(root, source, supporting_label, markdown_destination)
                    assert supporting is not None
                    supporting_links.append(
                        replace(
                            supporting,
                            link_index=link_index,
                            diagnostic=_link_diagnostic_message(link_code) if link_code is not None else None,
                        )
                    )
                    if link_code is not None:
                        diagnostics.append(_diagnostic(link_code, _link_diagnostic_message(link_code), source_path, line_number, source_excerpt, link_destination=markdown_destination if link_code != "SUPPORTING_LINK_UNSAFE" else None, link_index=link_index, link_kind="markdown"))
                    elif len(parsed_links) == 1:
                        legacy, _ = _linked_metadata(root, source, markdown_destination)
                        if legacy is not None:
                            diagnostics.append(_diagnostic("LEGACY_TYPED_TASK_LINK", _link_diagnostic_message("LEGACY_TYPED_TASK_LINK"), source_path, line_number, source_excerpt, link_destination=markdown_destination, link_index=link_index, link_kind="markdown"))
                else:
                    interior = parsed_link.group(3)
                    assert interior is not None
                    supporting, link_code = _wiki_supporting_link(root, source, interior)
                    supporting_links.append(
                        replace(
                            supporting,
                            link_index=link_index,
                            diagnostic=_link_diagnostic_message(link_code) if link_code is not None else None,
                        )
                    )
                    if link_code is not None:
                        diagnostics.append(_diagnostic(link_code, _link_diagnostic_message(link_code), source_path, line_number, source_excerpt, link_destination=interior, link_index=link_index, link_kind="wiki"))

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
                    supporting_links=tuple(supporting_links),
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
        diagnostics=tuple(sorted(diagnostics, key=_diagnostic_sort_key)),
        effective_allowed_roots=_DEFAULT_ALLOWED_ROOTS,
        effective_exclusions=effective_exclusions,
    )


_DIAGNOSTIC_CODE_RANK = {
    "TYPED_TASK_LINK_CARDINALITY": 0,
    "MALFORMED_TYPED_TASK_LINK": 1,
    "LEGACY_TYPED_TASK_LINK": 2,
    "UNSAFE_TASK_LINK": 3,
    "MISSING_TASK_RECORD": 3,
    "UNTYPED_TASK_RECORD": 3,
    "WRONG_TASK_RECORD_TYPE": 3,
    "CHECKBOX_STATUS_DISAGREEMENT": 3,
    "DUPLICATE_LINKED_TASK_RECORD": 3,
    "SUPPORTING_LINK_MISSING": 4,
    "SUPPORTING_LINK_UNSAFE": 5,
    "SUPPORTING_LINK_NON_MARKDOWN": 6,
    "SUPPORTING_WIKI_LINK_MALFORMED": 7,
    "SUPPORTING_WIKI_LINK_UNSAFE": 8,
    "SUPPORTING_WIKI_LINK_MISSING": 9,
    "SUPPORTING_WIKI_LINK_AMBIGUOUS": 10,
}


def _diagnostic_sort_key(diagnostic: CheckboxTaskDiagnostic) -> tuple[str, int, int, int, int, str]:
    checkbox_level = diagnostic.link_index is None
    return (
        diagnostic.source_path,
        diagnostic.line,
        0 if checkbox_level else 1,
        diagnostic.link_index if diagnostic.link_index is not None else -1,
        _DIAGNOSTIC_CODE_RANK.get(diagnostic.code, len(_DIAGNOSTIC_CODE_RANK)),
        diagnostic.code,
    )
