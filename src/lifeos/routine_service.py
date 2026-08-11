import calendar
import json
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos.domain import AuditRecord, Routine, RoutineSkip, Task


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
    raise ValueError("Unsupported cadence; use daily, weekly, or monthly")


def generate_routine_tasks(session: Session, routine: Routine, through: date, actor: str) -> int:
    generated = 0
    while routine.status == "active" and routine.next_run_date <= through:
        occurrence = routine.next_run_date
        occurrence_key = f"routine:{routine.id}:{occurrence.isoformat()}"
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
            task = Task(
                title=routine.title,
                status="open",
                due_date=occurrence,
                task_list_id=routine.task_list_id,
                goal_id=routine.goal_id,
                routine_id=routine.id,
                occurrence_key=occurrence_key,
            )
            session.add(task)
            session.flush()
            session.add(
                AuditRecord(
                    entity_type="task",
                    entity_id=task.id,
                    action="created",
                    actor=actor,
                    payload=json.dumps({"routine_id": routine.id, "occurrence_date": occurrence.isoformat()}),
                )
            )
            generated += 1
        routine.next_run_date = advance_occurrence(occurrence, routine.cadence)
    session.commit()
    return generated


def generate_all_routines(session: Session, through: date, actor: str) -> int:
    routines = session.scalars(select(Routine).where(Routine.status == "active").order_by(Routine.id))
    return sum(generate_routine_tasks(session, routine, through, actor) for routine in routines)
