import os
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from lifeos.task_api import get_actor
from lifeos.wiki_links import resolve_wiki_link

router = APIRouter(prefix="/api/sources")
view_router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_UNORDERED_ITEM = re.compile(r"^[-*+]\s+(.+)$")
_ORDERED_ITEM = re.compile(r"^\d+[.)]\s+(.+)$")
_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_MARKDOWN_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(([^\s)]+)(?:\s+[^)]*)?\)")
_INLINE_CODE = re.compile(r"`([^`]+)`")


def _source_url(path: str) -> str:
    return f"/sources/wiki/{quote(path, safe='/')}"


def _render_text(text: str) -> str:
    """Escape text while rendering the safe inline-code subset."""
    return _INLINE_CODE.sub(lambda match: f"<code>{escape(match.group(1))}</code>", escape(text))


def _link_target(
    target: str, *, current_path: str, wiki_root: Path, wikilink: bool
) -> tuple[str | None, str | None, bool]:
    """Return a safe href, diagnostic, and whether the target is external."""
    parsed = urlsplit(target)
    if parsed.scheme:
        if parsed.scheme in {"http", "https", "mailto"}:
            return target, None, True
        return None, "Unsafe link scheme", False
    if parsed.netloc:
        return None, "Protocol-relative links are not supported", False
    if not parsed.path:
        return parsed.fragment and f"#{quote(unquote(parsed.fragment), safe='')}", None, False

    raw_path = unquote(parsed.path)
    if raw_path.startswith("/") or "\\" in raw_path:
        return None, "Wiki link escapes wiki root", False
    requested = Path(raw_path)
    if requested.suffix.casefold() != ".md":
        if wikilink and not requested.suffix:
            requested = requested.with_suffix(".md")
        else:
            return None, "Wiki link target is not Markdown", False

    candidates: list[Path] = []
    if wikilink:
        candidates.extend([wiki_root / requested, (wiki_root / current_path).parent / requested])
        if len(requested.parts) == 1:
            candidates.extend(
                path for path in wiki_root.rglob("*.md") if path.name.casefold() == requested.name.casefold()
            )
    else:
        candidates.append((wiki_root / current_path).parent / requested)

    resolved_paths: dict[Path, str] = {}
    diagnostics: list[str] = []
    for candidate in candidates:
        try:
            relative = candidate.relative_to(wiki_root).as_posix()
            result = resolve_wiki_link(relative, wiki_root)
        except ValueError:
            diagnostics.append("Wiki link escapes wiki root")
            continue
        except HTTPException as exc:
            diagnostics.append(str(exc.detail))
            continue
        if result["available"]:
            resolved_paths[candidate.resolve()] = str(result["path"])
        elif result["diagnostic"]:
            diagnostics.append(str(result["diagnostic"]))

    if len(resolved_paths) == 1:
        path = next(iter(resolved_paths.values()))
        fragment = f"#{quote(unquote(parsed.fragment), safe='')}" if parsed.fragment else ""
        return _source_url(path) + fragment, None, False
    if len(resolved_paths) > 1:
        return None, f"Ambiguous wiki link target: {target}", False
    for diagnostic in diagnostics:
        if "escapes wiki root" in diagnostic:
            return None, "Wiki link escapes wiki root", False
        if diagnostic == "Canonical wiki source is symlink-unsafe":
            return None, diagnostic, False
    return None, f"Missing wiki link target: {target}", False


def _render_inline(text: str, *, current_path: str, wiki_root: Path) -> str:
    matches = list(_WIKILINK.finditer(text)) + list(_MARKDOWN_LINK.finditer(text))
    matches.sort(key=lambda match: match.start())
    output: list[str] = []
    position = 0
    for match in matches:
        if match.start() < position:
            continue
        output.append(_render_text(text[position : match.start()]))
        if match.re is _WIKILINK:
            target, label = match.group(1).strip(), (match.group(2) or match.group(1)).strip()
            href, diagnostic, external = _link_target(
                target, current_path=current_path, wiki_root=wiki_root, wikilink=True
            )
        else:
            label, target = match.group(1), match.group(2)
            href, diagnostic, external = _link_target(
                target, current_path=current_path, wiki_root=wiki_root, wikilink=False
            )
        if href:
            attrs = ' rel="noopener noreferrer"' if external else ""
            external_cue = '<span class="sr-only"> (external)</span>' if external else ""
            output.append(f'<a href="{escape(href, quote=True)}"{attrs}>{escape(label)}{external_cue}</a>')
        else:
            title = escape(diagnostic or "Unavailable link", quote=True)
            output.append(
                f'<span class="wiki-link-diagnostic" role="note">'
                f'<span aria-hidden="true">⚠</span> {escape(label)}: {title}</span>'
            )
        position = match.end()
    output.append(_render_text(text[position:]))
    return "".join(output)


def render_wiki_markdown(content: str, *, current_path: str, wiki_root: Path) -> str:
    """Render a deliberately small, escaped Markdown subset for authenticated wiki viewing."""
    lines = content.splitlines()
    if len(lines) > 1 and lines[0] == "---":
        try:
            lines = lines[lines.index("---", 1) + 1 :]
        except ValueError:
            pass
    output: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    code_lines: list[str] | None = None

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            rendered = _render_inline(" ".join(paragraph), current_path=current_path, wiki_root=wiki_root)
            output.append(f"<p>{rendered}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            output.append(f"</{list_kind}>")
            list_kind = None

    for line in lines:
        if line.startswith("```"):
            flush_paragraph()
            close_list()
            if code_lines is None:
                code_lines = []
            else:
                output.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")
                code_lines = None
            continue
        if code_lines is not None:
            code_lines.append(line)
            continue
        if not line.strip():
            flush_paragraph()
            close_list()
            continue
        heading = _HEADING.match(line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            rendered = _render_inline(heading.group(2), current_path=current_path, wiki_root=wiki_root)
            output.append(f"<h{level}>{rendered}</h{level}>")
            continue
        item = _UNORDERED_ITEM.match(line) or _ORDERED_ITEM.match(line)
        if item:
            flush_paragraph()
            kind = "ul" if _UNORDERED_ITEM.match(line) else "ol"
            if list_kind != kind:
                close_list()
                output.append(f"<{kind}>")
                list_kind = kind
            output.append(f"<li>{_render_inline(item.group(1), current_path=current_path, wiki_root=wiki_root)}</li>")
            continue
        close_list()
        paragraph.append(line.strip())
    flush_paragraph()
    close_list()
    if code_lines is not None:
        output.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")
    return "\n".join(output)


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
    candidate = (wiki_root / str(resolved["path"])).resolve()
    content = candidate.read_text(encoding="utf-8", errors="replace")
    rendered = render_wiki_markdown(content, current_path=str(resolved["path"]), wiki_root=wiki_root)
    source_path = str(resolved["path"] or path)
    section = None
    if source_path.startswith("01-Projects/"):
        section = {"label": "Projects", "href": "/projects"}
    elif source_path.startswith("02-Areas/"):
        section = {"label": "Areas", "href": "/areas"}
    return templates.TemplateResponse(
        request=request,
        name="canonical_source.html",
        context={
            "username": _actor,
            "title": candidate.stem,
            "source_path": source_path,
            "rendered": rendered,
            "section": section,
        },
    )
