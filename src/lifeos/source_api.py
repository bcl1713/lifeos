import os
from datetime import datetime, timezone
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


@router.get("/wiki/content")
def read_wiki_source(
    path: str = Query(min_length=1, max_length=500),
    _actor: str = Depends(get_actor),
) -> dict[str, str | bool | int]:
    resolved = resolve_wiki_path(path)
    if not resolved["available"]:
        return resolved
    if not path.lower().endswith(".md"):
        raise HTTPException(status_code=400, detail="Only Markdown sources can be previewed")
    wiki_root = Path(os.getenv("LIFEOS_WIKI_ROOT", "/wiki")).resolve()
    candidate = (wiki_root / path).resolve()
    content = candidate.read_text(encoding="utf-8", errors="replace")
    max_bytes = 64 * 1024
    encoded = content.encode("utf-8")
    truncated = len(encoded) > max_bytes
    if truncated:
        content = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return {
        "path": path,
        "available": True,
        "content": content,
        "truncated": truncated,
        "bytes": len(encoded),
        "modified_at": datetime.fromtimestamp(candidate.stat().st_mtime, timezone.utc).isoformat(),
    }


@router.get("/wiki/list")
def list_wiki_sources(
    prefix: str = Query(default="", max_length=300),
    limit: int = Query(default=100, ge=1, le=500),
    _actor: str = Depends(get_actor),
) -> list[dict[str, str | int]]:
    wiki_root = Path(os.getenv("LIFEOS_WIKI_ROOT", "/wiki")).resolve()
    base = (wiki_root / prefix).resolve()
    try:
        base.relative_to(wiki_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Source path escapes wiki root") from exc
    if not base.exists():
        return []
    if not base.is_dir():
        raise HTTPException(status_code=400, detail="Source prefix is not a directory")
    results = []
    for candidate in sorted(base.rglob("*.md"))[:limit]:
        relative = candidate.relative_to(wiki_root).as_posix()
        results.append({"path": relative, "bytes": candidate.stat().st_size})
    return results
