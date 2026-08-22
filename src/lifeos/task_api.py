import json
from uuid import uuid4
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lifeos.domain import AuditRecord, Goal, Project, Routine, Task, TaskDependency, TaskList, utcnow
from lifeos.wiki_store import WikiConflictError, WikiReconciliationRequiredError, WikiRepository, slugify

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
    owner_wiki_id: str | None = Field(default=None, max_length=300)
    owner_type: Literal["project", "area", "inbox"] | None = None


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
    owner_wiki_id: str | None = Field(default=None, max_length=300)
    owner_type: Literal["project", "area", "inbox"] | None = None
    expected_hash: str | None = Field(default=None, min_length=64, max_length=64)


class TaskDependencyCreate(BaseModel):
    depends_on_task_id: int
    expected_hash: str | None = Field(default=None, min_length=64, max_length=64)


def get_session(request: Request):
    with request.app.state.session_factory() as session:
        session.info["wiki_repository"] = request.app.state.wiki_repository
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
        "owner_wiki_id": task.owner_wiki_id,
        "owner_type": task.owner_type,
        "wiki_id": task.wiki_id,
        "wiki_path": task.wiki_path,
        "wiki_hash": task.wiki_hash,
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


def projection_reconciliation_required(
    session: Session,
    item: Any,
    entity: str,
    exc: Exception,
    *,
    wiki_id: str | None = None,
    wiki_path: str | None = None,
) -> None:
    if wiki_id is None or wiki_path is None:
        state = getattr(item, "_sa_instance_state", None)
        values = state.dict if state is not None else {}
        wiki_id = wiki_id if wiki_id is not None else values.get("wiki_id")
        wiki_path = wiki_path if wiki_path is not None else values.get("wiki_path")
    session.rollback()
    raise HTTPException(
        status_code=503,
        detail={
            "code": "canonical_source_written_projection_failed",
            "message": f"Canonical {entity} was written, but the projection failed; reconciliation is required",
            "wiki_id": wiki_id,
            "wiki_path": wiki_path,
        },
    ) from exc


def raise_reconciliation_required(exc: WikiReconciliationRequiredError) -> None:
    raise HTTPException(
        status_code=503,
        detail={
            "code": "canonical_source_written_projection_failed",
            "message": str(exc),
            "wiki_id": exc.wiki_id,
            "wiki_path": exc.wiki_path,
        },
    ) from exc


def sync_task_to_wiki(
    session: Session,
    task: Task,
    expected_hash: str | None = None,
    dependency_wiki_ids: list[str] | None = None,
) -> None:
    repository: WikiRepository | None = session.info.get("wiki_repository")
    if repository is None:
        raise HTTPException(status_code=503, detail="Canonical wiki repository is not configured")
    with session.no_autoflush:
        dependency_ids = dependency_wiki_ids if dependency_wiki_ids is not None else [
            wiki_id
            for wiki_id in session.scalars(
                select(Task.wiki_id)
                .join(TaskDependency, TaskDependency.depends_on_task_id == Task.id)
                .where(TaskDependency.task_id == task.id)
                .order_by(TaskDependency.id)
            )
            if wiki_id
        ]
        try:
            linked = repository.read(task.wiki_path) if task.wiki_path else None
        except FileNotFoundError:
            linked = None
        if task.wiki_path and linked is None:
            raise WikiConflictError("Canonical wiki path disappeared")
        if linked is not None and linked.record_type != "task":
            raise WikiConflictError("Canonical wiki path is not a task")
        if task.wiki_id:
            existing = repository.find_by_id(task.wiki_id)
            if existing is None:
                raise WikiConflictError("Canonical wiki record disappeared")
            if linked is not None and linked.record_id != existing.record_id:
                raise WikiConflictError("Canonical wiki identity and path disagree")
            record_id = existing.record_id
            task.wiki_id, task.wiki_path = existing.record_id, existing.path
        elif linked is not None:
            record_id = linked.record_id
            task.wiki_id, task.wiki_path = linked.record_id, linked.path
        else:
            record_id = f"tsk-{slugify(task.title)}"
            if repository.find_by_id(record_id) is not None:
                record_id = f"{record_id}-{uuid4().hex[:8]}"
        fields = {
            "id": record_id,
            "status": task.status,
            "notes": task.notes,
            "priority": task.priority,
            "tags": json.loads(task.tags or "[]"),
            "source_ref": task.source_ref,
            "due_date": task.due_date,
            "task_list": task.task_list.name,
            "goal_wiki_id": task.goal.wiki_id if task.goal else None,
            "project_wiki_id": task.project.wiki_id if task.project else None,
            "routine_wiki_id": task.routine.wiki_id if task.routine else None,
            "parent_wiki_id": task.parent.wiki_id if task.parent else None,
            "owner_wiki_id": task.owner_wiki_id,
            "owner_type": task.owner_type,
            "occurrence_key": task.occurrence_key,
            "depends_on": dependency_ids,
        }
        existing = repository.find_by_id(task.wiki_id) if task.wiki_id else None
        if existing is not None:
            task.wiki_id, task.wiki_path = existing.record_id, existing.path
            fields["id"] = existing.record_id
        record = repository.write("task", task.title, fields, path=task.wiki_path, expected_hash=expected_hash)
    task.wiki_id, task.wiki_path, task.wiki_hash = record.record_id, record.path, record.content_hash


def validate_task_links(session: Session, values: dict[str, Any]) -> None:
    related = (("goal_id", Goal), ("project_id", Project), ("routine_id", Routine))
    for field, model in related:
        value = values.get(field)
        if value is not None and session.get(model, value) is None:
            raise HTTPException(status_code=404, detail=f"{model.__name__} not found")


def resolve_task_owner(
    repository: WikiRepository, task_list: TaskList, owner_type: str | None, owner_wiki_id: str | None
) -> tuple[str | None, str | None, Any | None]:
    if owner_type is None and task_list.name == "Inbox":
        owner_type = "inbox"
    if owner_type == "inbox":
        if task_list.name != "Inbox" or owner_wiki_id is not None:
            raise HTTPException(status_code=422, detail="Inbox ownership requires the Inbox task list and no owner_wiki_id")
        return "inbox", None, None
    if owner_type not in {"project", "area"} or not owner_wiki_id:
        raise HTTPException(status_code=422, detail="non-Inbox tasks require an explicit Project or Area owner")
    owner = repository.find_by_id(owner_wiki_id)
    if owner is None or owner.record_type != owner_type:
        raise HTTPException(status_code=422, detail="task owner does not resolve to the declared canonical type")
    return owner_type, owner.record_id, owner


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


def create_canonical_task(
    session: Session,
    payload: TaskCreate,
    actor: str,
    *,
    record_id: str | None = None,
    occurrence_key: str | None = None,
    audit_payload: dict[str, Any] | None = None,
    audit_action: str = "created",
    initial_status: str = "open",
    expected_hash: str | None = None,
    commit: bool = True,
    enforce_owner: bool = True,
) -> Task:
    task_list = session.get(TaskList, payload.task_list_id)
    if task_list is None:
        raise HTTPException(status_code=404, detail="Task list not found")
    validate_task_links(session, payload.model_dump())
    repository: WikiRepository | None = session.info.get("wiki_repository")
    if repository is None:
        raise HTTPException(status_code=503, detail="Canonical wiki repository is not configured")
    values = payload.model_dump()
    if enforce_owner:
        owner_type, owner_wiki_id, owner = resolve_task_owner(
            repository, task_list, payload.owner_type, payload.owner_wiki_id
        )
    else:
        owner_type, owner_wiki_id, owner = payload.owner_type, payload.owner_wiki_id, None
    values["owner_type"] = owner_type
    values["owner_wiki_id"] = owner_wiki_id
    values["status"] = initial_status
    values["tags"] = json.dumps(values["tags"], sort_keys=True)
    canonical_id = record_id or f"tsk-{slugify(payload.title)}"
    if record_id is None and repository.find_by_id(canonical_id) is not None:
        canonical_id = f"{canonical_id}-{uuid4().hex[:8]}"
    related = {
        "goal_wiki_id": session.get(Goal, payload.goal_id).wiki_id if payload.goal_id else None,
        "project_wiki_id": session.get(Project, payload.project_id).wiki_id if payload.project_id else None,
        "routine_wiki_id": session.get(Routine, payload.routine_id).wiki_id if payload.routine_id else None,
        "parent_wiki_id": session.get(Task, payload.parent_id).wiki_id if payload.parent_id else None,
    }
    record = repository.write(
        "task",
        payload.title,
        {
            "id": canonical_id,
            "status": initial_status,
            "notes": payload.notes,
            "priority": payload.priority,
            "tags": payload.tags,
            "source_ref": payload.source_ref,
            "due_date": payload.due_date,
            "task_list": task_list.name,
            "owner_wiki_id": owner_wiki_id,
            "owner_type": owner_type,
            **related,
            "occurrence_key": occurrence_key,
            "depends_on": [],
        },
        path=repository.task_path(owner, payload.title, canonical_id) if enforce_owner else None,
        expected_hash=expected_hash,
    )
    task = Task(
        **values,
        occurrence_key=occurrence_key,
        wiki_id=record.record_id,
        wiki_path=record.path,
        wiki_hash=record.content_hash,
    )
    session.add(task)
    try:
        session.flush()
        add_audit(
            session,
            task_id=task.id,
            action=audit_action,
            actor=actor,
            payload=audit_payload or payload.model_dump(),
        )
        if commit:
            session.commit()
            session.refresh(task)
    except Exception as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "canonical_source_written_projection_failed",
                "message": "Canonical task was written, but the projection failed; reconciliation is required",
                "wiki_id": record.record_id,
                "wiki_path": record.path,
            },
        ) from exc
    return task


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return serialize_task(create_canonical_task(session, payload, actor))


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
    expected_hash = changes.pop("expected_hash", None)
    if not expected_hash:
        raise HTTPException(status_code=409, detail="expected_hash is required for canonical task mutation")
    if "tags" in changes:
        changes["tags"] = json.dumps(changes["tags"], sort_keys=True)
    if "task_list_id" in changes and session.get(TaskList, changes["task_list_id"]) is None:
        raise HTTPException(status_code=404, detail="Task list not found")
    if "owner_wiki_id" in changes or "owner_type" in changes:
        if changes.get("owner_wiki_id", task.owner_wiki_id) != task.owner_wiki_id or changes.get("owner_type", task.owner_type) != task.owner_type:
            raise HTTPException(status_code=409, detail="task owner changes require the controlled relocation workflow")
        changes.pop("owner_wiki_id", None)
        changes.pop("owner_type", None)
    validate_task_links(session, changes)
    for field, value in changes.items():
        setattr(task, field, value)
    try:
        sync_task_to_wiki(session, task, expected_hash)
    except WikiReconciliationRequiredError as exc:
        session.rollback()
        raise_reconciliation_required(exc)
    except WikiConflictError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        add_audit(session, task_id=task.id, action="updated", actor=actor, payload=changes)
        session.commit()
    except Exception as exc:
        projection_reconciliation_required(session, task, "task", exc)
    session.refresh(task)
    return serialize_task(task)


@router.post("/tasks/{task_id}/complete")
def complete_task(
    task_id: int,
    expected_hash: str | None = Query(default=None),
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _set_task_status(
        session, task_id=task_id, status_value="completed", action="completed", actor=actor, expected_hash=expected_hash
    )


@router.post("/tasks/{task_id}/pause")
def pause_task(
    task_id: int,
    expected_hash: str | None = Query(default=None),
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _set_task_status(session, task_id=task_id, status_value="paused", action="paused", actor=actor, expected_hash=expected_hash)


@router.post("/tasks/{task_id}/cancel")
def cancel_task(
    task_id: int,
    expected_hash: str | None = Query(default=None),
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _set_task_status(session, task_id=task_id, status_value="cancelled", action="cancelled", actor=actor, expected_hash=expected_hash)


@router.post("/tasks/{task_id}/archive")
def archive_task(
    task_id: int,
    expected_hash: str | None = Query(default=None),
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _set_task_status(session, task_id=task_id, status_value="archived", action="archived", actor=actor, expected_hash=expected_hash)


@router.post("/tasks/{task_id}/reopen")
def reopen_task(
    task_id: int,
    expected_hash: str | None = Query(default=None),
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _set_task_status(session, task_id=task_id, status_value="open", action="reopened", actor=actor, expected_hash=expected_hash)


def _set_task_status(
    session: Session,
    *,
    task_id: int,
    status_value: str,
    action: str,
    actor: str,
    expected_hash: str | None,
) -> dict[str, Any]:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not expected_hash:
        raise HTTPException(status_code=409, detail="expected_hash is required for canonical task mutation")
    if status_value == "completed":
        dependencies = session.scalars(select(TaskDependency).where(TaskDependency.task_id == task_id))
        unfinished = [
            dependency.depends_on_task_id
            for dependency in dependencies
            if (dependency_task := session.get(Task, dependency.depends_on_task_id)) is not None
            and dependency_task.status not in {"completed", "cancelled", "archived"}
        ]
        if unfinished:
            raise HTTPException(
                status_code=409, detail={"message": "Task has unfinished dependencies", "task_ids": unfinished}
            )
    task.status = status_value
    task.updated_at = utcnow()
    try:
        sync_task_to_wiki(session, task, expected_hash)
    except WikiReconciliationRequiredError as exc:
        session.rollback()
        raise_reconciliation_required(exc)
    except WikiConflictError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        add_audit(session, task_id=task.id, action=action, actor=actor, payload={"status": status_value})
        session.commit()
    except Exception as exc:
        projection_reconciliation_required(session, task, "task", exc)
    session.refresh(task)
    return serialize_task(task)


def _dependency_resource(item: TaskDependency) -> dict[str, Any]:
    return {
        "id": item.id,
        "task_id": item.task_id,
        "depends_on_task_id": item.depends_on_task_id,
        "created_at": item.created_at,
    }


def _would_create_cycle(session: Session, task_id: int, depends_on_task_id: int) -> bool:
    seen: set[int] = set()
    pending = [depends_on_task_id]
    while pending:
        current = pending.pop()
        if current == task_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(
            session.scalars(select(TaskDependency.depends_on_task_id).where(TaskDependency.task_id == current))
        )
    return False


@router.get("/tasks/{task_id}/dependencies")
def list_dependencies(
    task_id: int,
    _actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    if session.get(Task, task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return [
        _dependency_resource(item)
        for item in session.scalars(
            select(TaskDependency).where(TaskDependency.task_id == task_id).order_by(TaskDependency.id)
        )
    ]


@router.post("/tasks/{task_id}/dependencies", status_code=status.HTTP_201_CREATED)
def add_dependency(
    task_id: int,
    payload: TaskDependencyCreate,
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    task = session.get(Task, task_id)
    prerequisite = session.get(Task, payload.depends_on_task_id)
    if task is None or prerequisite is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not payload.expected_hash:
        raise HTTPException(status_code=409, detail="expected_hash is required for canonical dependency mutation")
    if task_id == payload.depends_on_task_id or _would_create_cycle(session, task_id, payload.depends_on_task_id):
        raise HTTPException(status_code=409, detail="Task dependency would create a cycle")
    existing = session.scalar(
        select(TaskDependency).where(
            TaskDependency.task_id == task_id,
            TaskDependency.depends_on_task_id == payload.depends_on_task_id,
        )
    )
    if existing is not None:
        return _dependency_resource(existing)
    dependency_ids = [
        wiki_id
        for wiki_id in session.scalars(
            select(Task.wiki_id)
            .join(TaskDependency, TaskDependency.depends_on_task_id == Task.id)
            .where(TaskDependency.task_id == task_id)
            .order_by(TaskDependency.id)
        )
        if wiki_id
    ]
    dependency_ids.append(prerequisite.wiki_id)
    try:
        sync_task_to_wiki(session, task, payload.expected_hash, dependency_ids)
    except WikiReconciliationRequiredError as exc:
        session.rollback()
        raise_reconciliation_required(exc)
    except WikiConflictError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        item = TaskDependency(task_id=task_id, depends_on_task_id=payload.depends_on_task_id)
        session.add(item)
        session.flush()
        add_audit(
            session,
            task_id=task_id,
            action="dependency_added",
            actor=actor,
            payload={"depends_on_task_id": payload.depends_on_task_id},
        )
        session.commit()
    except Exception as exc:
        projection_reconciliation_required(session, task, "task", exc)
    session.refresh(item)
    return _dependency_resource(item)


@router.delete("/tasks/{task_id}/dependencies/{dependency_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_dependency(
    task_id: int,
    dependency_id: int,
    expected_hash: str | None = Query(default=None),
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> None:
    item = session.get(TaskDependency, dependency_id)
    if item is None or item.task_id != task_id:
        raise HTTPException(status_code=404, detail="Dependency not found")
    if not expected_hash:
        raise HTTPException(status_code=409, detail="expected_hash is required for canonical dependency mutation")
    task = session.get(Task, task_id)
    remaining_ids = [
        wiki_id
        for wiki_id in session.scalars(
            select(Task.wiki_id)
            .join(TaskDependency, TaskDependency.depends_on_task_id == Task.id)
            .where(TaskDependency.task_id == task_id, TaskDependency.id != dependency_id)
            .order_by(TaskDependency.id)
        )
        if wiki_id
    ]
    try:
        sync_task_to_wiki(session, task, expected_hash, remaining_ids)
    except WikiReconciliationRequiredError as exc:
        session.rollback()
        raise_reconciliation_required(exc)
    except WikiConflictError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        session.delete(item)
        session.flush()
        add_audit(
            session, task_id=task_id, action="dependency_removed", actor=actor, payload={"dependency_id": dependency_id}
        )
        session.commit()
    except Exception as exc:
        projection_reconciliation_required(session, task, "task", exc)


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
