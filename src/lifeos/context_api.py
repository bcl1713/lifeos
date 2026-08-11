from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos.domain import Goal, Project, Routine, TaskList
from lifeos.routine_service import generate_all_routines, generate_routine_tasks
from lifeos.task_api import get_actor, get_session

router = APIRouter(prefix="/api")


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: str | None = Field(default=None, min_length=1, max_length=30)


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    goal_id: int | None = None


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: str | None = Field(default=None, min_length=1, max_length=30)
    goal_id: int | None = None


class RoutineCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    cadence: str = Field(min_length=1, max_length=50)
    start_date: date
    task_list_id: int
    goal_id: int | None = None


class RoutineUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    cadence: str | None = Field(default=None, min_length=1, max_length=50)
    status: str | None = Field(default=None, min_length=1, max_length=30)
    task_list_id: int | None = None
    goal_id: int | None = None


def _require_goal(session: Session, goal_id: int | None) -> None:
    if goal_id is not None and session.get(Goal, goal_id) is None:
        raise HTTPException(status_code=404, detail="Goal not found")


def _resource(resource: Any) -> dict[str, Any]:
    values = {column.name: getattr(resource, column.name) for column in resource.__table__.columns}
    return values


@router.get("/goals")
def list_goals(_actor: str = Depends(get_actor), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_resource(goal) for goal in session.scalars(select(Goal).order_by(Goal.id))]


@router.post("/goals", status_code=status.HTTP_201_CREATED)
def create_goal(
    payload: GoalCreate, _actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> dict[str, Any]:
    goal = Goal(title=payload.title.strip())
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return _resource(goal)


@router.patch("/goals/{goal_id}")
def update_goal(
    goal_id: int, payload: GoalUpdate, _actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> dict[str, Any]:
    goal = session.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(goal, field, value.strip() if isinstance(value, str) and field == "title" else value)
    session.commit()
    session.refresh(goal)
    return _resource(goal)


@router.get("/projects")
def list_projects(_actor: str = Depends(get_actor), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_resource(project) for project in session.scalars(select(Project).order_by(Project.id))]


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate, _actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> dict[str, Any]:
    _require_goal(session, payload.goal_id)
    project = Project(title=payload.title.strip(), goal_id=payload.goal_id)
    session.add(project)
    session.commit()
    session.refresh(project)
    return _resource(project)


@router.patch("/projects/{project_id}")
def update_project(
    project_id: int, payload: ProjectUpdate, _actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> dict[str, Any]:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    changes = payload.model_dump(exclude_unset=True)
    _require_goal(session, changes.get("goal_id", project.goal_id))
    for field, value in changes.items():
        setattr(project, field, value.strip() if isinstance(value, str) and field == "title" else value)
    session.commit()
    session.refresh(project)
    return _resource(project)


@router.get("/routines")
def list_routines(_actor: str = Depends(get_actor), session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_resource(routine) for routine in session.scalars(select(Routine).order_by(Routine.id))]


@router.post("/routines", status_code=status.HTTP_201_CREATED)
def create_routine(
    payload: RoutineCreate,
    _actor: str = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_goal(session, payload.goal_id)
    if session.get(TaskList, payload.task_list_id) is None:
        raise HTTPException(status_code=404, detail="Task list not found")
    routine = Routine(
        title=payload.title.strip(),
        cadence=payload.cadence.strip(),
        next_run_date=payload.start_date,
        task_list_id=payload.task_list_id,
        goal_id=payload.goal_id,
    )
    session.add(routine)
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


@router.patch("/routines/{routine_id}")
def update_routine(
    routine_id: int, payload: RoutineUpdate, _actor: str = Depends(get_actor), session: Session = Depends(get_session)
) -> dict[str, Any]:
    routine = session.get(Routine, routine_id)
    if routine is None:
        raise HTTPException(status_code=404, detail="Routine not found")
    changes = payload.model_dump(exclude_unset=True)
    _require_goal(session, changes.get("goal_id", routine.goal_id))
    if "task_list_id" in changes and session.get(TaskList, changes["task_list_id"]) is None:
        raise HTTPException(status_code=404, detail="Task list not found")
    for field, value in changes.items():
        setattr(routine, field, value.strip() if isinstance(value, str) and field in {"title", "cadence"} else value)
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
