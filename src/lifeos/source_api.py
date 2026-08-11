import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from lifeos.task_api import get_actor

router = APIRouter(prefix="/api/sources")


def resolve_wiki_path(path: str, root: Path | None = None) -> dict[str, str | bool]:
    wiki_root = (root or Path(os.getenv("LIFEOS_WIKI_ROOT", "/wiki"))).resolve()
    candidate = (wiki_root / path).resolve()
    try:
        candidate.relative_to(wiki_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Source path escapes wiki root") from exc
    if not candidate.exists():
        return {"path": path, "available": False}
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail="Source path is not a file")
    return {"path": path, "available": True, "url": f"/sources/wiki/{path}"}


@router.get("/wiki")
def resolve_wiki_source(path: str = Query(min_length=1, max_length=500), _actor: str = Depends(get_actor)):
    return resolve_wiki_path(path)
