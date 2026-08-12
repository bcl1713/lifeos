from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from lifeos.task_api import get_actor, get_session
from lifeos.wiki_store import WikiConflictError, WikiRepository

router = APIRouter(prefix="/api")


class AreaCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    status: str = Field(default="active", max_length=50)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    summary: str = ""


class AreaUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: str | None = Field(default=None, max_length=50)
    aliases: list[str] | None = Field(default=None, max_length=20)
    summary: str | None = None
    expected_hash: str = Field(min_length=64, max_length=64)


def _area(record) -> dict[str, Any]:
    return {
        "id": record.record_id,
        "title": record.title,
        "status": record.fields.get("status", "active"),
        "aliases": record.fields.get("aliases", []),
        "summary": record.body,
        "wiki_path": record.path,
        "wiki_hash": record.content_hash,
    }


def _repo(session) -> WikiRepository:
    repository = session.info.get("wiki_repository")
    if repository is None:
        raise HTTPException(status_code=503, detail="Wiki is not configured")
    return repository


@router.get("/areas")
def list_areas(_actor: str = Depends(get_actor), session=Depends(get_session)) -> list[dict[str, Any]]:
    return [_area(record) for record in _repo(session).list_records("area")]


@router.post("/areas", status_code=status.HTTP_201_CREATED)
def create_area(payload: AreaCreate, actor: str = Depends(get_actor), session=Depends(get_session)) -> dict[str, Any]:
    repository = _repo(session)
    if repository.find_by_title("area", payload.title.strip()) is not None:
        raise HTTPException(status_code=409, detail="Area already exists")
    record = repository.write(
        "area",
        payload.title.strip(),
        {"status": payload.status, "aliases": payload.aliases},
        f"# {payload.title.strip()}\n\n{payload.summary.strip()}\n",
    )
    return _area(record)


@router.patch("/areas/{area_id}")
def update_area(area_id: str, payload: AreaUpdate, actor: str = Depends(get_actor), session=Depends(get_session)) -> dict[str, Any]:
    repository = _repo(session)
    record = repository.find_by_id(area_id)
    if record is None or record.record_type != "area":
        raise HTTPException(status_code=404, detail="Area not found")
    changes = payload.model_dump(exclude_unset=True)
    expected_hash = changes.pop("expected_hash", None)
    title = str(changes.pop("title", record.title))
    fields = dict(record.fields)
    fields.update(changes)
    body = record.body
    if "summary" in changes:
        body = f"# {title}\n\n{changes['summary']}\n"
        fields.pop("summary", None)
    try:
        updated = repository.write("area", title, fields, body, path=record.path, expected_hash=expected_hash)
    except WikiConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _area(updated)
