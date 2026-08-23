"""Read-only retirement inventory for legacy Goals and Routines projections.

This module deliberately has no apply mode. It only reports mappings that an
operator can review before creating owner-local recurrence metadata elsewhere.
"""

from __future__ import annotations

from typing import Any, Never

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos.domain import Goal, Routine, Task, TaskList
from lifeos.wiki_store import WikiRepository

_RETIREMENT_CODE = "legacy_domain_retired"


def raise_legacy_domain_retired(domain: str) -> Never:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": _RETIREMENT_CODE,
            "message": (
                f"{domain.title()} are retired; use Projects, Areas, Inbox tasks, and the dry-run legacy report."
            ),
            "report_path": "/api/legacy/goals-routines/report",
        },
    )


def _source(item: Goal | Routine) -> dict[str, int | str | None]:
    return {"table": item.__tablename__, "row_id": item.id, "wiki_id": item.wiki_id}


def _recurrence_metadata(routine: Routine) -> dict[str, Any]:
    return {
        "cadence": routine.cadence,
        "next_run_date": routine.next_run_date.isoformat(),
        "minimum_occurrences": routine.minimum_occurrences,
        "frequency_window_days": routine.frequency_window_days,
        "skips": [
            {"scheduled_date": skip.scheduled_date.isoformat(), "reason": skip.reason}
            for skip in sorted(routine.skips, key=lambda item: (item.scheduled_date, item.id))
        ],
    }


def _routine_target(
    session: Session, repository: WikiRepository | None, routine: Routine
) -> tuple[dict[str, str | None] | None, dict[str, Any] | None]:
    task_list = session.get(TaskList, routine.task_list_id)
    owners = sorted(
        {
            (task.owner_type, task.owner_wiki_id)
            for task in session.scalars(select(Task).where(Task.routine_id == routine.id))
            if task.owner_type in {"project", "area"} and task.owner_wiki_id
        }
    )
    source = _source(routine)
    if len(owners) > 1:
        return None, {
            "source": source,
            "code": "routine_owner_ambiguous",
            "message": "Routine occurrences resolve to multiple Project or Area task owners",
        }
    if owners:
        owner_type, owner_wiki_id = owners[0]
        owner = repository.find_by_id(owner_wiki_id) if repository is not None else None
        if owner is None or owner.record_type != owner_type:
            return None, {
                "source": source,
                "code": "routine_owner_unresolved",
                "message": "Routine task owner does not resolve to the declared canonical Project or Area",
            }
        return {"owner_type": owner_type, "owner_wiki_id": owner_wiki_id}, None
    if task_list is not None and task_list.name == "Inbox":
        return {"owner_type": "inbox", "owner_wiki_id": None}, None
    return None, {
        "source": source,
        "code": "routine_owner_unresolved",
        "message": "Routine has no explicit Project or Area task owner and is not in Inbox",
    }


def legacy_retirement_report(session: Session, repository: WikiRepository | None = None) -> dict[str, Any]:
    """Return a deterministic, side-effect-free inventory of retired rows."""
    goals = list(session.scalars(select(Goal).order_by(Goal.id)))
    routines = list(session.scalars(select(Routine).order_by(Routine.id)))
    mappings: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    for routine in routines:
        target, exception = _routine_target(session, repository, routine)
        if exception is not None:
            exceptions.append(exception)
            continue
        mappings.append(
            {"source": _source(routine), "target": target, "recurrence_metadata": _recurrence_metadata(routine)}
        )
    return {
        "mode": "dry-run",
        "writes_performed": False,
        "legacy_goals": [
            {"source": _source(goal), "action": "archive", "title": goal.title, "status": goal.status} for goal in goals
        ],
        "routine_mappings": mappings,
        "blocking_exceptions": exceptions,
        "summary": {
            "legacy_goals": len(goals),
            "legacy_routines": len(routines),
            "ready_mappings": len(mappings),
            "blocking_exceptions": len(exceptions),
        },
    }
