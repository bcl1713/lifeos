import json
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from lifeos.domain import WikiContextItem
from lifeos.task_api import get_actor, get_session

router = APIRouter(prefix="/api")


def _item(item: WikiContextItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "source_type": item.source_type,
        "source_id": item.source_id,
        "title": item.title,
        "wiki_path": item.wiki_path,
        "wiki_url": item.wiki_url,
        "status": item.status,
        "aliases": json.loads(item.aliases),
        "summary": item.summary,
        "content_hash": item.content_hash,
        "modified_at": item.modified_at,
        "stale": item.stale,
        "indexed_at": item.indexed_at,
    }


@router.get("/wiki-context")
def list_wiki_context(
    source_type: str | None = None,
    include_stale: bool = False,
    _actor: str = Depends(get_actor),
    session=Depends(get_session),
) -> list[dict[str, Any]]:
    query = select(WikiContextItem).order_by(WikiContextItem.source_type, WikiContextItem.title)
    if source_type:
        query = query.where(WikiContextItem.source_type == source_type)
    if not include_stale:
        query = query.where(WikiContextItem.stale.is_(False))
    return [_item(item) for item in session.scalars(query)]


@router.post("/wiki-sync")
def sync_wiki(
    _actor: str = Depends(get_actor),
    session=Depends(get_session),
) -> dict[str, int]:
    from lifeos.scripts_bridge import sync_wiki_projection

    repository = session.info.get("wiki_repository")
    if repository is None:
        return {"created": 0, "updated": 0, "stale": 0, "unchanged": 0}
    return sync_wiki_projection(session, repository)
