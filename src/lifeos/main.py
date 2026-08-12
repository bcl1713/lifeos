import os

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from pydantic import BaseModel

from lifeos import __version__
from lifeos.area_api import router as area_router
from lifeos.auth import AuthService
from lifeos.context_api import router as context_router
from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.metric_api import router as metric_router
from lifeos.scheduler import scheduler_lifespan
from lifeos.source_api import router as source_router, view_router as source_view_router
from lifeos.task_api import router as task_router
from lifeos.ui import router as ui_router
from lifeos.wiki_context_api import router as wiki_context_router

_SESSION_COOKIE = "lifeos_session"


class LoginRequest(BaseModel):
    username: str
    password: str


def create_app(
    database_url: str | None = None,
    *,
    auth_username: str | None = None,
    auth_password: str | None = None,
    agent_token: str | None = None,
    scheduler_enabled: bool | None = None,
    scheduler_interval_seconds: int | None = None,
    wiki_root: str | None = None,
) -> FastAPI:
    database_url = database_url or os.getenv("DATABASE_URL", "sqlite:///./data/lifeos.db")
    engine = create_engine(database_url)
    initialize_database(engine)
    session_factory = create_session_factory(engine)
    auth = AuthService(session_factory)

    username = auth_username or os.getenv("LIFEOS_USERNAME")
    password = auth_password or os.getenv("LIFEOS_PASSWORD")
    if username and password:
        auth.ensure_user(username, password)

    configured_agent_token = agent_token or os.getenv("LIFEOS_AGENT_TOKEN")
    if configured_agent_token:
        auth.ensure_agent(configured_agent_token)

    scheduler_enabled = (
        scheduler_enabled if scheduler_enabled is not None else os.getenv("LIFEOS_SCHEDULER_ENABLED", "1") == "1"
    )
    scheduler_interval_seconds = scheduler_interval_seconds or int(
        os.getenv("LIFEOS_SCHEDULER_INTERVAL_SECONDS", "900")
    )
    app = FastAPI(
        title="LifeOS",
        version=__version__,
        lifespan=scheduler_lifespan if scheduler_enabled else None,
    )
    app.state.engine = engine
    app.state.auth = auth
    app.state.session_factory = session_factory
    app.state.scheduler_timezone = os.getenv("LIFEOS_TIMEZONE", "America/Chicago")
    app.state.scheduler_interval_seconds = scheduler_interval_seconds
    from lifeos.wiki_store import WikiRepository

    configured_wiki_root = wiki_root or os.getenv("LIFEOS_WIKI_ROOT")
    app.state.wiki_repository = WikiRepository(configured_wiki_root) if configured_wiki_root else None
    app.include_router(context_router)
    app.include_router(area_router)
    app.include_router(task_router)
    app.include_router(metric_router)
    app.include_router(source_router)
    app.include_router(source_view_router)
    app.include_router(wiki_context_router)
    app.include_router(ui_router)

    def require_user(request: Request) -> str:
        username = auth.get_session_username(request.cookies.get(_SESSION_COOKIE))
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        return username

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "lifeos",
            "version": os.getenv("LIFEOS_VERSION", __version__),
        }

    @app.post("/auth/login", status_code=status.HTTP_204_NO_CONTENT)
    def login(payload: LoginRequest, response: Response) -> None:
        token, authenticated = auth.create_session(payload.username, payload.password)
        if not authenticated:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        response.set_cookie(
            _SESSION_COOKIE,
            token,
            max_age=12 * 60 * 60,
            httponly=True,
            secure=os.getenv("LIFEOS_COOKIE_SECURE", "0") == "1",
            samesite="lax",
        )

    @app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(request: Request, response: Response) -> None:
        auth.revoke_session(request.cookies.get(_SESSION_COOKIE))
        response.delete_cookie(_SESSION_COOKIE)

    @app.get("/auth/me")
    def me(username: str = Depends(require_user)) -> dict[str, str]:
        return {"username": username}

    @app.get("/auth/agent")
    def agent_check(authorization: str | None = Header(default=None)) -> dict[str, str]:
        token = authorization.removeprefix("Bearer ") if authorization else None
        if not auth.authenticate_agent(token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Agent authentication required")
        return {"actor": "agent"}

    return app


app = create_app()
