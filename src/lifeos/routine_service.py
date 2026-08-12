import calendar
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos.domain import Routine, RoutineSkip, Task
from lifeos.task_api import TaskCreate, create_canonical_task
from lifeos.wiki_store import WikiConflictError, WikiReconciliationRequiredError, WikiRepository


def advance_occurrence(value: date, cadence: str) -> date:
    if cadence == "daily":
        return value + timedelta(days=1)
    if cadence == "weekly":
        return value + timedelta(days=7)
    if cadence == "monthly":
        month = value.month + 1
        year = value.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))
    if cadence.startswith("interval:"):
        days = int(cadence.removeprefix("interval:"))
        if days < 1:
            raise ValueError("Interval cadence must be at least one day")
        return value + timedelta(days=days)
    if cadence.startswith("weekdays:"):
        weekdays = {int(item) for item in cadence.removeprefix("weekdays:").split(",") if item != ""}
        if not weekdays or not weekdays <= set(range(7)):
            raise ValueError("Weekday cadence must use comma-separated days 0 through 6")
        candidate = value + timedelta(days=1)
        while candidate.weekday() not in weekdays:
            candidate += timedelta(days=1)
        return candidate
    raise ValueError("Unsupported cadence; use daily, weekly, monthly, interval:N, or weekdays:0,2,4")


def _resolve_canonical_routine(repository: WikiRepository, routine: Routine):
    try:
        linked = repository.read(routine.wiki_path) if routine.wiki_path else None
    except FileNotFoundError:
        linked = None
    if routine.wiki_path and linked is None:
        raise WikiConflictError("Canonical wiki path disappeared")
    if linked is not None and linked.record_type != "routine":
        raise WikiConflictError("Canonical wiki path is not a routine")
    if routine.wiki_id:
        existing = repository.find_by_id(routine.wiki_id)
        if existing is None:
            raise WikiConflictError("Canonical wiki record disappeared")
        if existing.record_type != "routine":
            raise WikiConflictError("Canonical wiki identity is not a routine")
        if linked is not None and linked.record_id != existing.record_id:
            raise WikiConflictError("Canonical wiki identity and path disagree")
    elif linked is not None:
        existing = linked
    else:
        raise WikiConflictError("Routine has no canonical wiki identity")
    routine.wiki_id, routine.wiki_path = existing.record_id, existing.path
    return existing


def generate_routine_tasks(session: Session, routine: Routine, through: date, actor: str) -> int:
    repository: WikiRepository | None = session.info.get("wiki_repository")
    if repository is None:
        raise RuntimeError("Canonical wiki repository is required for routine generation")
    current_routine = _resolve_canonical_routine(repository, routine)
    if current_routine.content_hash != routine.wiki_hash:
        raise WikiConflictError("Canonical wiki record changed since it was read")
    generated = 0
    written_task: Task | None = None
    try:
        while routine.status == "active" and routine.next_run_date <= through:
            occurrence = routine.next_run_date
            if not routine.wiki_id:
                raise RuntimeError("Routine has no canonical wiki identity")
            occurrence_key = f"routine:{routine.wiki_id}:{occurrence.isoformat()}"
            skipped = (
                session.scalar(
                    select(RoutineSkip).where(
                        RoutineSkip.routine_id == routine.id,
                        RoutineSkip.scheduled_date == occurrence,
                    )
                )
                is not None
            )
            existing = session.scalar(select(Task).where(Task.occurrence_key == occurrence_key))
            if existing is None and not skipped:
                written_task = create_canonical_task(
                    session,
                    TaskCreate(
                        title=routine.title,
                        due_date=occurrence,
                        task_list_id=routine.task_list_id,
                        goal_id=routine.goal_id,
                        routine_id=routine.id,
                    ),
                    actor,
                    record_id=f"tsk-{routine.wiki_id}-{occurrence.isoformat()}",
                    occurrence_key=occurrence_key,
                    audit_payload={"routine_id": routine.id, "occurrence_date": occurrence.isoformat()},
                    commit=False,
                )
                generated += 1
            routine.next_run_date = advance_occurrence(occurrence, routine.cadence)
            fields = dict(repository.read(routine.wiki_path).fields)
            fields["next_run_date"] = routine.next_run_date
            updated = repository.write(
                "routine",
                routine.title,
                fields,
                path=routine.wiki_path,
                expected_hash=routine.wiki_hash,
            )
            routine.wiki_hash = updated.content_hash
        session.commit()
    except Exception as exc:
        session.rollback()
        if written_task is not None and not isinstance(exc, WikiReconciliationRequiredError):
            raise WikiReconciliationRequiredError(
                "Canonical routine occurrence was written, but projection reconciliation is required",
                wiki_id=written_task.wiki_id,
                wiki_path=written_task.wiki_path,
            ) from exc
        raise
    return generated


def generate_all_routines(session: Session, through: date, actor: str) -> int:
    routines = session.scalars(select(Routine).where(Routine.status == "active").order_by(Routine.id))
    return sum(generate_routine_tasks(session, routine, through, actor) for routine in routines)
