import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lifeos.domain import (
    AuditRecord,
    Goal,
    GoalMilestone,
    Idea,
    Project,
    Resource,
    Routine,
    RoutineSkip,
    Task,
    TaskList,
)
from lifeos.routine_service import generate_all_routines, generate_routine_tasks
from lifeos.task_api import get_actor, get_session
from lifeos.wiki_store import WikiConflictError, WikiRepository

router = APIRouter(prefix="/api")


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    outcome: str | None = None
    baseline: str | None = None
    target: str | None = None
    rationale: str | None = None
    constraints: str | None = None
    review_cadence: str | None = Field(default=None, max_length=100)
    review_date: date | None = None
    adjustment_trigger: str | None = None


class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: Literal["not_started", "active", "blocked", "paused", "completed", "abandoned"] | None = None
    outcome: str | None = None
    baseline: str | None = None
    target: str | None = None
    rationale: str | None = None
    constraints: str | None = None
    review_cadence: str | None = Field(default=None, max_length=100)
    review_date: date | None = None
    adjustment_trigger: str | None = None
    expected_hash: str | None = Field(default=None, min_length=64, max_length=64)


class GoalMilestoneCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_date: date | None = None


class GoalMilestoneUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    due_date: date | None = None
    status: Literal["open", "completed", "abandoned"] | None = None


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    owner: str | None = Field(default=None, max_length=200)
    collaborators: str | None = None
    scope: str | None = None
    non_goals: str | None = None
    risks: str | None = None
    deadline: date | None = None
    review_trigger: str | None = None
    source_refs: str | None = None
    goal_id: int | None = None


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: Literal["active", "blocked", "paused", "completed", "abandoned", "archived"] | None = None
    owner: str | None = Field(default=None, max_length=200)
    collaborators: str | None = None
    scope: str | None = None
    non_goals: str | None = None
    risks: str | None = None
    deadline: date | None = None
    review_trigger: str | None = None
    source_refs: str | None = None
    goal_id: int | None = None
    expected_hash: str | None = Field(default=None, min_length=64, max_length=64)


class ResourceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    canonical_url: str | None = Field(default=None, max_length=1000)
    resource_type: str | None = Field(default=None, max_length=80)
    description: str | None = None
    accessed_at: date | None = None
    source_refs: str | None = None
    notes: str | None = None


class ResourceUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    canonical_url: str | None = Field(default=None, max_length=1000)
    resource_type: str | None = Field(default=None, max_length=80)
    status: Literal["active", "archived"] | None = None
    description: str | None = None
    accessed_at: date | None = None
    source_refs: str | None = None
    notes: str | None = None


class IdeaCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    rationale: str | None = None
    experiment: str | None = None
    next_action: str | None = None
    source_refs: str | None = None
    project_id: int | None = None


class IdeaUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: Literal["captured", "exploring", "promoted", "rejected", "parked"] | None = None
    rationale: str | None = None
    experiment: str | None = None
    next_action: str | None = None
    source_refs: str | None = None
    project_id: int | None = None


class RoutineCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    cadence: str = Field(min_length=1, max_length=50)
    start_date: date
    task_list_id: int
    goal_id: int | None = None
    minimum_occurrences: int | None = Field(default=None, ge=1, le=31)
    frequency_window_days: int | None = Field(default=None, ge=1, le=365)

    @model_validator(mode="after")
    def validate_frequency(self) -> "RoutineCreate":
        if (self.minimum_occurrences is None) != (self.frequency_window_days is None):
            raise ValueError("minimum_occurrences and frequency_window_days must be provided together")
        if self.minimum_occurrences and self.minimum_occurrences > self.frequency_window_days:
            raise ValueError("minimum_occurrences cannot exceed frequency_window_days")
        return self


class RoutineUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    cadence: str | None = Field(default=None, min_length=1, max_length=50)
    status: Literal["active", "paused", "archived"] | None = None
    task_list_id: int | None = None
    goal_id: int | None = None
    minimum_occurrences: int | None = Field(default=None, ge=1, le=31)
    frequency_window_days: int | None = Field(default=None, ge=1, le=365)
    expected_hash: str | None = Field(default=None, min_length=64, max_length=64)


class RoutineSkipCreate(BaseModel):
    scheduled_date: date
    reason: str | None = Field(default=None, max_length=300)


def _require_goal(session: Session, goal_id: int | None) -> None:
    if goal_id is not None and session.get(Goal, goal_id) is None:
        raise HTTPException(status_code=404, detail="Goal not found")


def _require_project(session: Session, project_id: int | None) -> None:
    if project_id is not None and session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")


def _resource(resource: Any) -> dict[str, Any]:
    values = {column.name: getattr(resource, column.name) for column in resource.__table__.columns}
    return values


def _goal_resource(session: Session, goal: Goal) -> dict[str, Any]:
    milestones = list(
        session.scalars(select(GoalMilestone).where(GoalMilestone.goal_id == goal.id).order_by(GoalMilestone.id))
    )
    result = _resource(goal)
    result["milestones_total"] = len(milestones)
    result["milestones_completed"] = sum(item.status == "completed" for item in milestones)
    result["progress"] = (
        round(result["milestones_completed"] / result["milestones_total"] * 100, 1) if milestones else None
    )
    result["milestones"] = [_resource(item) for item in milestones]
    return result


def _audit(
    session: Session, entity_type: str, entity_id: int, action: str, actor: str, payload: dict[str, Any]
) -> None:
    session.add(
        AuditRecord(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            payload=json.dumps(payload, default=str, sort_keys=True),
        )
    )


def _wiki_sync(session: Session, item: Any, record_type: str, expected_hash: str | None = None) -> None:
    repository: WikiRepository | None = session.info.get("wiki_repository")
    if repository is None:
        return
    excluded = {"id", "created_at", "updated_at", "wiki_id", "wiki_path", "wiki_hash", "title"}
    fields = {column.name: getattr(item, column.name) for column in item.__table__.columns if column.name not in excluded}
    fields["id"] = item.wiki_id or f"{record_type[:3]}-{item.id}"
    existing = repository.find_by_id(item.wiki_id) if item.wiki_id else repository.find_by_title(record_type, item.title)
    if existing is not None:
        item.wiki_id, item.wiki_path = existing.record_id, existing.path
        fields["id"] = existing.record_id
    record = repository.write(record_type, item.title, fields, path=item.wiki_path, expected_hash=expected_hash)
    item.wiki_id, item.wiki_path, item.wiki_hash = record.record_id, record.path, record.content_hash


@router.get("/goals")
def list_goals(_actor: str = Depends(get_actor), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_goal_resource(session, goal) for goal in session.scalars(select(Goal).order_by(Goal.id))]


@router.post("/goals", status_code=status.HTTP_201_CREATED)
def create_goal(
    payload: GoalCreate, actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> dict[str, Any]:
    values = payload.model_dump()
    values["title"] = values["title"].strip()
    goal = Goal(**values)
    session.add(goal)
    session.flush()
    _wiki_sync(session, goal, "goal")
    _audit(session, "goal", goal.id, "created", actor, values)
    session.commit()
    session.refresh(goal)
    return _goal_resource(session, goal)


@router.patch("/goals/{goal_id}")
def update_goal(
    goal_id: int, payload: GoalUpdate, actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> dict[str, Any]:
    goal = session.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    changes = payload.model_dump(exclude_unset=True)
    expected_hash = changes.pop("expected_hash", None)
    for field, value in changes.items():
        setattr(goal, field, value.strip() if isinstance(value, str) and field == "title" else value)
    try:
        _wiki_sync(session, goal, "goal", expected_hash)
    except WikiConflictError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(session, "goal", goal.id, "updated", actor, changes)
    session.commit()
    session.refresh(goal)
    return _goal_resource(session, goal)


@router.post("/goals/{goal_id}/milestones", status_code=status.HTTP_201_CREATED)
def create_milestone(
    goal_id: int,
    payload: GoalMilestoneCreate,
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if session.get(Goal, goal_id) is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    milestone = GoalMilestone(goal_id=goal_id, title=payload.title.strip(), due_date=payload.due_date)
    session.add(milestone)
    session.flush()
    _audit(session, "goal_milestone", milestone.id, "created", actor, payload.model_dump())
    session.commit()
    session.refresh(milestone)
    return _resource(milestone)


@router.patch("/goals/{goal_id}/milestones/{milestone_id}")
def update_milestone(
    goal_id: int,
    milestone_id: int,
    payload: GoalMilestoneUpdate,
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    milestone = session.get(GoalMilestone, milestone_id)
    if milestone is None or milestone.goal_id != goal_id:
        raise HTTPException(status_code=404, detail="Milestone not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(milestone, field, value.strip() if field == "title" and isinstance(value, str) else value)
    if "status" in changes:
        milestone.completed_at = datetime.now(timezone.utc) if changes["status"] == "completed" else None
    _audit(session, "goal_milestone", milestone.id, "updated", actor, changes)
    session.commit()
    session.refresh(milestone)
    return _resource(milestone)


@router.get("/projects")
def list_projects(_actor: str = Depends(get_actor), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_resource(project) for project in session.scalars(select(Project).order_by(Project.id))]


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate, actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> dict[str, Any]:
    _require_goal(session, payload.goal_id)
    values = payload.model_dump()
    values["title"] = values["title"].strip()
    project = Project(**values)
    session.add(project)
    session.flush()
    _wiki_sync(session, project, "project")
    _audit(session, "project", project.id, "created", actor, values)
    session.commit()
    session.refresh(project)
    return _resource(project)


@router.patch("/projects/{project_id}")
def update_project(
    project_id: int, payload: ProjectUpdate, actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> dict[str, Any]:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    changes = payload.model_dump(exclude_unset=True)
    expected_hash = changes.pop("expected_hash", None)
    _require_goal(session, changes.get("goal_id", project.goal_id))
    for field, value in changes.items():
        setattr(project, field, value.strip() if isinstance(value, str) and field == "title" else value)
    try:
        _wiki_sync(session, project, "project", expected_hash)
    except WikiConflictError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(session, "project", project.id, "updated", actor, changes)
    session.commit()
    session.refresh(project)
    return _resource(project)


@router.get("/resources")
def list_resources(_actor: str = Depends(get_actor), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_resource(resource) for resource in session.scalars(select(Resource).order_by(Resource.id))]


@router.post("/resources", status_code=status.HTTP_201_CREATED)
def create_resource(
    payload: ResourceCreate, actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> dict[str, Any]:
    values = payload.model_dump()
    values["title"] = values["title"].strip()
    resource = Resource(**values)
    session.add(resource)
    session.flush()
    _audit(session, "resource", resource.id, "created", actor, values)
    session.commit()
    session.refresh(resource)
    return _resource(resource)


@router.patch("/resources/{resource_id}")
def update_resource(
    resource_id: int, payload: ResourceUpdate, actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> dict[str, Any]:
    resource = session.get(Resource, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(resource, field, value.strip() if field == "title" and isinstance(value, str) else value)
    _audit(session, "resource", resource.id, "updated", actor, changes)
    session.commit()
    session.refresh(resource)
    return _resource(resource)


@router.get("/ideas")
def list_ideas(_actor: str = Depends(get_actor), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_resource(idea) for idea in session.scalars(select(Idea).order_by(Idea.id))]


@router.post("/ideas", status_code=status.HTTP_201_CREATED)
def create_idea(
    payload: IdeaCreate, actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> dict[str, Any]:
    _require_project(session, payload.project_id)
    values = payload.model_dump()
    values["title"] = values["title"].strip()
    idea = Idea(**values)
    session.add(idea)
    session.flush()
    _audit(session, "idea", idea.id, "created", actor, values)
    session.commit()
    session.refresh(idea)
    return _resource(idea)


@router.patch("/ideas/{idea_id}")
def update_idea(
    idea_id: int, payload: IdeaUpdate, actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> dict[str, Any]:
    idea = session.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found")
    changes = payload.model_dump(exclude_unset=True)
    _require_project(session, changes.get("project_id", idea.project_id))
    for field, value in changes.items():
        setattr(idea, field, value.strip() if field == "title" and isinstance(value, str) else value)
    _audit(session, "idea", idea.id, "updated", actor, changes)
    session.commit()
    session.refresh(idea)
    return _resource(idea)


@router.get("/routines")
def list_routines(_actor: str = Depends(get_actor), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_resource(routine) for routine in session.scalars(select(Routine).order_by(Routine.id))]


@router.post("/routines", status_code=status.HTTP_201_CREATED)
def create_routine(
    payload: RoutineCreate,
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_goal(session, payload.goal_id)
    if session.get(TaskList, payload.task_list_id) is None:
        raise HTTPException(status_code=404, detail="Task list not found")
    routine = Routine(
        title=payload.title.strip(),
        cadence=payload.cadence.strip(),
        next_run_date=payload.start_date,
        minimum_occurrences=payload.minimum_occurrences,
        frequency_window_days=payload.frequency_window_days,
        task_list_id=payload.task_list_id,
        goal_id=payload.goal_id,
    )
    session.add(routine)
    session.flush()
    _wiki_sync(session, routine, "routine")
    _audit(session, "routine", routine.id, "created", actor, {"title": routine.title, "cadence": routine.cadence})
    session.commit()
    session.refresh(routine)
    return _resource(routine)


@router.post("/routines/generate")
def generate_all(
    on: date | None = Query(default=None),
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, int]:
    try:
        generated = generate_all_routines(session, on or date.today(), actor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"generated": generated}


@router.get("/routines/{routine_id}/frequency")
def routine_frequency(
    routine_id: int,
    on: date | None = Query(default=None),
    _actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    routine = session.get(Routine, routine_id)
    if routine is None:
        raise HTTPException(status_code=404, detail="Routine not found")
    if routine.minimum_occurrences is None or routine.frequency_window_days is None:
        raise HTTPException(status_code=409, detail="Routine has no minimum-frequency target")
    end_date = on or date.today()
    start_date = end_date - timedelta(days=routine.frequency_window_days - 1)
    completed = (
        session.scalar(
            select(func.count(Task.id)).where(
                Task.routine_id == routine_id,
                Task.status == "completed",
                Task.due_date >= start_date,
                Task.due_date <= end_date,
            )
        )
        or 0
    )
    required = routine.minimum_occurrences
    compliance = "on_target" if completed >= required else "recovering" if completed > 0 else "missed"
    return {
        "routine_id": routine_id,
        "window_start": start_date,
        "window_end": end_date,
        "window_days": routine.frequency_window_days,
        "required_occurrences": required,
        "completed_occurrences": completed,
        "remaining_occurrences": max(required - completed, 0),
        "compliance": compliance,
    }


@router.post("/routines/{routine_id}/skip", status_code=status.HTTP_201_CREATED)
def skip_routine(
    routine_id: int,
    payload: RoutineSkipCreate,
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    routine = session.get(Routine, routine_id)
    if routine is None:
        raise HTTPException(status_code=404, detail="Routine not found")
    existing = session.scalar(
        select(RoutineSkip).where(
            RoutineSkip.routine_id == routine_id,
            RoutineSkip.scheduled_date == payload.scheduled_date,
        )
    )
    if existing is not None:
        return {
            "id": existing.id,
            "routine_id": routine_id,
            "scheduled_date": existing.scheduled_date,
            "reason": existing.reason,
        }
    skip = RoutineSkip(routine_id=routine_id, scheduled_date=payload.scheduled_date, reason=payload.reason)
    session.add(skip)
    session.flush()
    _audit(session, "routine", routine.id, "skipped", actor, payload.model_dump())
    session.commit()
    return {"id": skip.id, "routine_id": routine_id, "scheduled_date": skip.scheduled_date, "reason": skip.reason}


@router.patch("/routines/{routine_id}")
def update_routine(
    routine_id: int, payload: RoutineUpdate, actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> dict[str, Any]:
    routine = session.get(Routine, routine_id)
    if routine is None:
        raise HTTPException(status_code=404, detail="Routine not found")
    changes = payload.model_dump(exclude_unset=True)
    expected_hash = changes.pop("expected_hash", None)
    _require_goal(session, changes.get("goal_id", routine.goal_id))
    if "task_list_id" in changes and session.get(TaskList, changes["task_list_id"]) is None:
        raise HTTPException(status_code=404, detail="Task list not found")
    minimum = changes.get("minimum_occurrences", routine.minimum_occurrences)
    window = changes.get("frequency_window_days", routine.frequency_window_days)
    if (minimum is None) != (window is None) or (minimum is not None and minimum > window):
        raise HTTPException(status_code=422, detail="minimum_occurrences and frequency_window_days must be provided together")
    for field, value in changes.items():
        setattr(routine, field, value.strip() if isinstance(value, str) and field in {"title", "cadence"} else value)
    try:
        _wiki_sync(session, routine, "routine", expected_hash)
    except WikiConflictError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(session, "routine", routine.id, "updated", actor, changes)
    session.commit()
    session.refresh(routine)
    return _resource(routine)


@router.post("/routines/{routine_id}/generate")
def generate_routine(
    routine_id: int,
    on: date | None = Query(default=None),
    actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    routine = session.get(Routine, routine_id)
    if routine is None:
        raise HTTPException(status_code=404, detail="Routine not found")
    try:
        generated = generate_routine_tasks(session, routine, on or date.today(), actor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"routine_id": routine.id, "generated": generated}
