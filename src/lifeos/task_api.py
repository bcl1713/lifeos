import json
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifeos.domain import AuditRecord, Goal, Project, Routine, Task, TaskList, utcnow

router = APIRouter(prefix="/api")


class TaskListCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    task_list_id: int
    notes: str | None = None
    priority: int = Field(default=0, ge=0, le=3)
    tags: list[str] = Field(default_factory=list, max_length=20)
    source_ref: str | None = Field(default=None, max_length=500)
    due_date: date | None = None
    goal_id: int | None = None
    project_id: int | None = None
    routine_id: int | None = None
    parent_id: int | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    notes: str | None = None
    priority: int | None = Field(default=None, ge=0, le=3)
    tags: list[str] | None = Field(default=None, max_length=20)
    source_ref: str | None = Field(default=None, max_length=500)
    due_date: date | None = None
    task_list_id: int | None = None
    goal_id: int | None = None
    project_id: int | None = None
    routine_id: int | None = None
    parent_id: int | None = None


def get_session(request: Request):
    with request.app.state.session_factory() as session:
        yield session


def get_actor(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    auth = request.app.state.auth
    username = auth.get_session_username(request.cookies.get("lifeos_session"))
    if username:
        return username
    token = authorization.removeprefix("Bearer ") if authorization else None
    if auth.authenticate_agent(token):
        return "agent"
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


def serialize_task(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "notes": task.notes,
        "status": task.status,
        "priority": task.priority,
        "tags": json.loads(task.tags or "[]"),
        "source_ref": task.source_ref,
        "due_date": task.due_date,
        "task_list_id": task.task_list_id,
        "goal_id": task.goal_id,
        "project_id": task.project_id,
        "routine_id": task.routine_id,
        "parent_id": task.parent_id,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def add_audit(session: Session, *, task_id: int, action: str, actor: str, payload: dict[str, Any]) -> None:
    session.add(
        AuditRecord(
            entity_type="task",
            entity_id=task_id,
            action=action,
            actor=actor,
            payload=json.dumps(payload, default=str, sort_keys=True),
        )
    )


def validate_task_links(session: Session, values: dict[str, Any]) -> None:
    related = (("goal_id", Goal), ("project_id", Project), ("routine_id", Routine))
    for field, model in related:
        value = values.get(field)
        if value is not None and session.get(model, value) is None:
            raise HTTPException(status_code=404, detail=f"{model.__name__} not found")


@router.get("/task-lists")
def list_task_lists(
    _actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    return [{"id": item.id, "name": item.name} for item in session.scalars(select(TaskList).order_by(TaskList.name))]


@router.post("/task-lists", status_code=status.HTTP_201_CREATED)
def create_task_list(
    payload: TaskListCreate,
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = TaskList(name=payload.name.strip())
    session.add(item)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Task list already exists") from exc
    session.refresh(item)
    return {"id": item.id, "name": item.name}


@router.get("/tasks")
def list_tasks(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    query = select(Task).order_by(Task.due_date.is_(None), Task.due_date, Task.id).offset(offset).limit(limit)
    if status_filter:
        query = query.where(Task.status == status_filter)
    return [serialize_task(task) for task in session.scalars(query)]


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if session.get(TaskList, payload.task_list_id) is None:
        raise HTTPException(status_code=404, detail="Task list not found")
    validate_task_links(session, payload.model_dump())
    values = payload.model_dump()
    values["tags"] = json.dumps(values["tags"], sort_keys=True)
    task = Task(**values)
    session.add(task)
    try:
        session.flush()
        add_audit(session, task_id=task.id, action="created", actor=actor, payload=payload.model_dump())
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Task already exists in this task list") from exc
    session.refresh(task)
    return serialize_task(task)


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: int,
    payload: TaskUpdate,
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    changes = payload.model_dump(exclude_unset=True)
    if "tags" in changes:
        changes["tags"] = json.dumps(changes["tags"], sort_keys=True)
    if "task_list_id" in changes and session.get(TaskList, changes["task_list_id"]) is None:
        raise HTTPException(status_code=404, detail="Task list not found")
    validate_task_links(session, changes)
    for field, value in changes.items():
        setattr(task, field, value)
    try:
        session.flush()
        add_audit(session, task_id=task.id, action="updated", actor=actor, payload=changes)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Task already exists in this task list") from exc
    session.refresh(task)
    return serialize_task(task)


@router.post("/tasks/{task_id}/complete")
def complete_task(
    task_id: int,
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _set_task_status(session, task_id=task_id, status_value="completed", action="completed", actor=actor)


@router.post("/tasks/{task_id}/pause")
def pause_task(
    task_id: int,
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _set_task_status(session, task_id=task_id, status_value="paused", action="paused", actor=actor)


@router.post("/tasks/{task_id}/cancel")
def cancel_task(
    task_id: int,
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _set_task_status(session, task_id=task_id, status_value="cancelled", action="cancelled", actor=actor)


@router.post("/tasks/{task_id}/archive")
def archive_task(
    task_id: int,
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _set_task_status(session, task_id=task_id, status_value="archived", action="archived", actor=actor)


@router.post("/tasks/{task_id}/reopen")
def reopen_task(
    task_id: int,
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _set_task_status(session, task_id=task_id, status_value="open", action="reopened", actor=actor)


def _set_task_status(session: Session, *, task_id: int, status_value: str, action: str, actor: str) -> dict[str, Any]:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = status_value
    task.updated_at = utcnow()
    add_audit(session, task_id=task.id, action=action, actor=actor, payload={"status": status_value})
    session.commit()
    session.refresh(task)
    return serialize_task(task)


@router.get("/tasks/{task_id}/audit")
def task_audit(
    task_id: int,
    _actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    if session.get(Task, task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    records = session.scalars(
        select(AuditRecord)
        .where(AuditRecord.entity_type == "task", AuditRecord.entity_id == task_id)
        .order_by(AuditRecord.id)
    )
    return [
        {
            "id": record.id,
            "action": record.action,
            "actor": record.actor,
            "payload": record.payload,
            "created_at": record.created_at,
        }
        for record in records
    ]
