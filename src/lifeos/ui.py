from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lifeos.domain import AuditRecord, Goal, MetricDefinition, MetricEntry, Project, Routine, Task, TaskList, utcnow

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def get_session(request: Request):
    with request.app.state.session_factory() as session:
        yield session


def require_user(request: Request) -> str:
    username = request.app.state.auth.get_session_username(request.cookies.get("lifeos_session"))
    if username is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return username


def redirect_login() -> RedirectResponse:
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


def ensure_default_list(session: Session) -> TaskList:
    item = session.scalar(select(TaskList).order_by(TaskList.id))
    if item is None:
        item = TaskList(name="Inbox")
        session.add(item)
        session.commit()
        session.refresh(item)
    return item


def render_tasks(request: Request, username: str, session: Session, *, all_tasks: bool = False) -> HTMLResponse:
    ensure_default_list(session)
    query = select(Task).order_by(Task.due_date.is_(None), Task.due_date, Task.id)
    if not all_tasks:
        query = query.where(Task.status == "open")
    tasks = list(session.scalars(query))
    task_lists = list(session.scalars(select(TaskList).order_by(TaskList.name)))
    template = "tasks.html" if all_tasks else "today.html"
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={"username": username, "tasks": tasks, "task_lists": task_lists, "today": date.today()},
    )


@router.get("/", response_class=HTMLResponse)
def home(request: Request, session: Session = Depends(get_session)) -> Response:
    username = request.app.state.auth.get_session_username(request.cookies.get("lifeos_session"))
    if username is None:
        return redirect_login()
    return render_tasks(request, username, session)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> Response:
    if request.app.state.auth.get_session_username(request.cookies.get("lifeos_session")):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None, "username": None})


@router.post("/login", response_class=HTMLResponse)
def login_form(request: Request, username: str = Form(...), password: str = Form(...)) -> Response:
    token, authenticated = request.app.state.auth.create_session(username, password)
    if not authenticated:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password", "username": None},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        "lifeos_session",
        token,
        max_age=12 * 60 * 60,
        httponly=True,
        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https",
        samesite="lax",
    )
    return response


@router.post("/ui/logout", status_code=status.HTTP_303_SEE_OTHER)
def ui_logout(request: Request) -> RedirectResponse:
    request.app.state.auth.revoke_session(request.cookies.get("lifeos_session"))
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("lifeos_session")
    return response


@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(
    request: Request, username: str = Depends(require_user), session: Session = Depends(get_session)
) -> HTMLResponse:
    return render_tasks(request, username, session, all_tasks=True)


@router.post("/ui/tasks", status_code=status.HTTP_303_SEE_OTHER)
def create_ui_task(
    request: Request,
    title: str = Form(...),
    task_list_id: int = Form(...),
    notes: str = Form(default=""),
    due_date: str = Form(default=""),
    username: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    if session.get(TaskList, task_list_id) is None:
        raise HTTPException(status_code=404, detail="Task list not found")
    parsed_due_date = date.fromisoformat(due_date) if due_date else None
    task = Task(title=title.strip(), notes=notes.strip() or None, due_date=parsed_due_date, task_list_id=task_list_id)
    session.add(task)
    session.flush()
    session.add(
        AuditRecord(entity_type="task", entity_id=task.id, action="created", actor=username, payload='{"source":"web"}')
    )
    session.commit()
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ui/tasks/{task_id}/complete", status_code=status.HTTP_303_SEE_OTHER)
def complete_ui_task(
    task_id: int, username: str = Depends(require_user), session: Session = Depends(get_session)
) -> RedirectResponse:
    return _set_ui_status(task_id, "completed", "completed", username, session)


@router.post("/ui/tasks/{task_id}/pause", status_code=status.HTTP_303_SEE_OTHER)
def pause_ui_task(
    task_id: int, username: str = Depends(require_user), session: Session = Depends(get_session)
) -> RedirectResponse:
    return _set_ui_status(task_id, "paused", "paused", username, session)


@router.post("/ui/tasks/{task_id}/cancel", status_code=status.HTTP_303_SEE_OTHER)
def cancel_ui_task(
    task_id: int, username: str = Depends(require_user), session: Session = Depends(get_session)
) -> RedirectResponse:
    return _set_ui_status(task_id, "cancelled", "cancelled", username, session)


@router.post("/ui/tasks/{task_id}/archive", status_code=status.HTTP_303_SEE_OTHER)
def archive_ui_task(
    task_id: int, username: str = Depends(require_user), session: Session = Depends(get_session)
) -> RedirectResponse:
    return _set_ui_status(task_id, "archived", "archived", username, session)


@router.post("/ui/tasks/{task_id}/reopen", status_code=status.HTTP_303_SEE_OTHER)
def reopen_ui_task(
    task_id: int, username: str = Depends(require_user), session: Session = Depends(get_session)
) -> RedirectResponse:
    return _set_ui_status(task_id, "open", "reopened", username, session)


def _set_ui_status(task_id: int, status_value: str, action: str, username: str, session: Session) -> RedirectResponse:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = status_value
    task.updated_at = utcnow()
    session.add(
        AuditRecord(
            entity_type="task",
            entity_id=task.id,
            action=action,
            actor=username,
            payload=f'{{"source":"web","status":"{status_value}"}}',
        )
    )
    session.commit()
    return RedirectResponse("/" if status_value == "completed" else "/tasks", status_code=status.HTTP_303_SEE_OTHER)


def render_context(
    request: Request, username: str, session: Session, title: str, singular: str, items: list, action: str
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="context.html",
        context={
            "username": username,
            "title": title,
            "singular": singular,
            "items": items,
            "action": action,
            "task_lists": list(session.scalars(select(TaskList).order_by(TaskList.name))),
        },
    )


@router.get("/goals", response_class=HTMLResponse)
def goals_page(
    request: Request, username: str = Depends(require_user), session: Session = Depends(get_session)
) -> HTMLResponse:
    return render_context(
        request, username, session, "Goals", "goal", list(session.scalars(select(Goal).order_by(Goal.id))), "/ui/goals"
    )


@router.post("/ui/goals", status_code=status.HTTP_303_SEE_OTHER)
def create_ui_goal(
    title: str = Form(...), username: str = Depends(require_user), session: Session = Depends(get_session)
) -> RedirectResponse:
    session.add(Goal(title=title.strip()))
    session.commit()
    return RedirectResponse("/goals", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/projects", response_class=HTMLResponse)
def projects_page(
    request: Request, username: str = Depends(require_user), session: Session = Depends(get_session)
) -> HTMLResponse:
    return render_context(
        request,
        username,
        session,
        "Projects",
        "project",
        list(session.scalars(select(Project).order_by(Project.id))),
        "/ui/projects",
    )


@router.post("/ui/projects", status_code=status.HTTP_303_SEE_OTHER)
def create_ui_project(
    title: str = Form(...),
    goal_id: str = Form(default=""),
    username: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    parsed_goal = int(goal_id) if goal_id else None
    if parsed_goal is not None and session.get(Goal, parsed_goal) is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    session.add(Project(title=title.strip(), goal_id=parsed_goal))
    session.commit()
    return RedirectResponse("/projects", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/routines", response_class=HTMLResponse)
def routines_page(
    request: Request, username: str = Depends(require_user), session: Session = Depends(get_session)
) -> HTMLResponse:
    ensure_default_list(session)
    return render_context(
        request,
        username,
        session,
        "Routines",
        "routine",
        list(session.scalars(select(Routine).order_by(Routine.id))),
        "/ui/routines",
    )


@router.post("/ui/routines", status_code=status.HTTP_303_SEE_OTHER)
def create_ui_routine(
    title: str = Form(...),
    cadence: str = Form(...),
    start_date: str = Form(...),
    task_list_id: int = Form(...),
    goal_id: str = Form(default=""),
    username: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    if session.get(TaskList, task_list_id) is None:
        raise HTTPException(status_code=404, detail="Task list not found")
    parsed_goal = int(goal_id) if goal_id else None
    if parsed_goal is not None and session.get(Goal, parsed_goal) is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    session.add(
        Routine(
            title=title.strip(),
            cadence=cadence.strip(),
            next_run_date=date.fromisoformat(start_date),
            task_list_id=task_list_id,
            goal_id=parsed_goal,
        )
    )
    session.commit()
    return RedirectResponse("/routines", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/data", response_class=HTMLResponse)
def data_page(
    request: Request, username: str = Depends(require_user), session: Session = Depends(get_session)
) -> HTMLResponse:
    counts = {
        "tasks": session.scalar(select(func.count()).select_from(Task)) or 0,
        "goals": session.scalar(select(func.count()).select_from(Goal)) or 0,
        "projects": session.scalar(select(func.count()).select_from(Project)) or 0,
        "routines": session.scalar(select(func.count()).select_from(Routine)) or 0,
        "metrics": session.scalar(select(func.count()).select_from(MetricDefinition)) or 0,
        "metric_entries": session.scalar(select(func.count()).select_from(MetricEntry)) or 0,
        "audit": session.scalar(select(func.count()).select_from(AuditRecord)) or 0,
    }
    audits = list(session.scalars(select(AuditRecord).order_by(AuditRecord.id.desc()).limit(20)))
    return templates.TemplateResponse(
        request=request, name="data.html", context={"username": username, "counts": counts, "audits": audits}
    )
