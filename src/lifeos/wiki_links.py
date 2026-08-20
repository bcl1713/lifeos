"""Validated canonical wiki links for API and browser surfaces."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException


def resolve_wiki_link(
    path: str,
    wiki_root: str | Path,
    *,
    silverbullet_base_url: str | None = None,
) -> dict[str, str | bool | None]:
    root = Path(wiki_root).resolve()
    unresolved = root / path
    candidate = unresolved.resolve()
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Source path escapes wiki root") from exc
    cursor = root
    for component in Path(path).parts:
        if component in {"", "."}:
            continue
        cursor /= component
        if cursor.is_symlink():
            return {
                "path": path,
                "available": False,
                "link_status": "unavailable",
                "canonical_url": None,
                "diagnostic": "Canonical wiki source is symlink-unsafe",
            }
    if not candidate.is_file():
        return {
            "path": path,
            "available": False,
            "link_status": "missing",
            "canonical_url": None,
            "diagnostic": "Canonical wiki source is missing",
        }
    if candidate.suffix.casefold() != ".md":
        return {
            "path": relative,
            "available": False,
            "link_status": "unavailable",
            "canonical_url": None,
            "diagnostic": "Canonical source is not Markdown",
        }
    if silverbullet_base_url:
        page = relative[:-3]
        url = f"{silverbullet_base_url.rstrip('/')}/{quote(page, safe='/')}"
    else:
        url = f"/sources/wiki/{quote(relative, safe='/')}"
    return {
        "path": relative,
        "available": True,
        "link_status": "valid",
        "canonical_url": url,
        "diagnostic": None,
    }
