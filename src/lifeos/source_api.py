import os
from html import escape
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from lifeos.task_api import get_actor
from lifeos.wiki_links import resolve_wiki_link

router = APIRouter(prefix="/api/sources")
view_router = APIRouter()


def resolve_wiki_path(path: str, root: Path | None = None) -> dict[str, str | bool | None]:
    wiki_root = (root or Path(os.getenv("LIFEOS_WIKI_ROOT", "/wiki"))).resolve()
    result = resolve_wiki_link(
        path,
        wiki_root,
        silverbullet_base_url=os.getenv("LIFEOS_SILVERBULLET_BASE_URL"),
    )
    result["url"] = result["canonical_url"]
    return result


def _wiki_root(request: Request) -> Path:
    repository = request.app.state.wiki_repository
    return repository.root if repository is not None else Path(os.getenv("LIFEOS_WIKI_ROOT", "/wiki")).resolve()


@router.get("/wiki")
def resolve_wiki_source(
    request: Request,
    path: str = Query(min_length=1, max_length=500),
    _actor: str = Depends(get_actor),
):
    return resolve_wiki_path(path, _wiki_root(request))


@router.get("/wiki/content")
def read_wiki_source(
    request: Request,
    path: str = Query(min_length=1, max_length=500),
    _actor: str = Depends(get_actor),
) -> dict[str, str | bool | int | None]:
    wiki_root = _wiki_root(request)
    resolved = resolve_wiki_path(path, wiki_root)
    if not resolved["available"]:
        return resolved
    if not path.lower().endswith(".md"):
        raise HTTPException(status_code=400, detail="Only Markdown sources can be previewed")
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
    request: Request,
    prefix: str = Query(default="", max_length=300),
    limit: int = Query(default=100, ge=1, le=500),
    _actor: str = Depends(get_actor),
) -> list[dict[str, str | int]]:
    wiki_root = _wiki_root(request)
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


@view_router.get("/sources/wiki/{path:path}", response_class=HTMLResponse)
def view_wiki_source(
    request: Request,
    path: str,
    _actor: str = Depends(get_actor),
) -> HTMLResponse:
    wiki_root = _wiki_root(request)
    resolved = resolve_wiki_path(path, wiki_root)
    if not resolved["available"]:
        raise HTTPException(status_code=404, detail=resolved["diagnostic"])
    candidate = (wiki_root / path).resolve()
    content = candidate.read_text(encoding="utf-8", errors="replace")
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'><title>"
        + escape(candidate.stem)
        + " · LifeOS</title></head><body><main><p><a href='javascript:history.back()'>Back to LifeOS</a></p>"
        + f"<p><code>{escape(resolved['path'] or path)}</code></p><pre>{escape(content)}</pre></main></body></html>"
    )
