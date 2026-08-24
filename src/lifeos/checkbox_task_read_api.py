"""Authenticated, scanner-authoritative checkbox task read model."""

from __future__ import annotations

import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from lifeos.task_api import get_actor
from lifeos.wiki_checkbox_tasks import (
    CheckboxTaskDiagnostic,
    CheckboxTaskScanResult,
    CheckboxTaskSnapshot,
    scan_checkbox_tasks,
)
from lifeos.wiki_links import resolve_wiki_link
from lifeos.wiki_store import WikiRepository

router = APIRouter(prefix="/api/v1")


def _link(path: str, repository: WikiRepository) -> dict[str, str | None]:
    resolved = resolve_wiki_link(
        path,
        repository.root,
        silverbullet_base_url=os.getenv("LIFEOS_SILVERBULLET_BASE_URL"),
    )
    return {
        "url": str(resolved["canonical_url"]) if resolved["available"] and resolved["canonical_url"] else None,
        "diagnostic": str(resolved["diagnostic"]) if resolved["diagnostic"] else None,
    }


def _source(task: CheckboxTaskSnapshot, repository: WikiRepository) -> dict[str, str | int | None]:
    return {
        "path": task.source_path,
        "line": task.line,
        "column": task.column,
        "excerpt": task.source_excerpt,
        **_link(task.source_path, repository),
    }


def _task(task: CheckboxTaskSnapshot, repository: WikiRepository) -> dict[str, object]:
    linked_record = None
    if task.linked_task_path is not None:
        linked_record = {
            "id": task.linked_task_id,
            "title": task.linked_task_title,
            "summary": task.linked_task_summary,
            "priority": task.linked_task_priority,
            "path": task.linked_task_path,
            **_link(task.linked_task_path, repository),
        }
    return {
        "checked": task.checked,
        "label": task.label,
        "content_fingerprint": task.content_fingerprint,
        "identity": task.identity,
        "source": _source(task, repository),
        "linked_record": linked_record,
    }


def _diagnostic(diagnostic: CheckboxTaskDiagnostic, repository: WikiRepository) -> dict[str, object]:
    linked_record = None
    if diagnostic.linked_record_path is not None:
        linked_record = {"path": diagnostic.linked_record_path, **_link(diagnostic.linked_record_path, repository)}
    return {
        "code": diagnostic.code,
        "severity": diagnostic.severity,
        "message": diagnostic.message,
        "link_destination": diagnostic.link_destination,
        "source": {
            "path": diagnostic.source_path,
            "line": diagnostic.line,
            "column": diagnostic.column,
            "excerpt": diagnostic.source_excerpt,
            **_link(diagnostic.source_path, repository),
        },
        "linked_record": linked_record,
    }


def checkbox_task_read_model(repository: WikiRepository) -> dict[str, object]:
    """Produce the UI/API DTO exclusively from the canonical wiki scanner."""
    result: CheckboxTaskScanResult = scan_checkbox_tasks(repository.root)
    return {
        "tasks": [_task(task, repository) for task in result.tasks],
        "diagnostics": [_diagnostic(diagnostic, repository) for diagnostic in result.diagnostics],
        "policy": {
            "allowed_roots": list(result.effective_allowed_roots),
            "exclusions": list(result.effective_exclusions),
        },
    }


def get_checkbox_task_read_model(request: Request) -> dict[str, object]:
    repository: WikiRepository | None = request.app.state.wiki_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="Canonical wiki repository is not configured")
    return checkbox_task_read_model(repository)


@router.get("/checkbox-tasks")
def list_checkbox_tasks(
    state: Literal["all", "open", "checked"] = Query(default="all"),
    _actor: str = Depends(get_actor),
    model: dict[str, object] = Depends(get_checkbox_task_read_model),
) -> dict[str, object]:
    tasks = model["tasks"]
    assert isinstance(tasks, list)
    if state == "open":
        tasks = [task for task in tasks if not task["checked"]]
    elif state == "checked":
        tasks = [task for task in tasks if task["checked"]]
    return {**model, "tasks": tasks}
