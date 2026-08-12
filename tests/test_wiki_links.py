from pathlib import Path

import pytest
from fastapi import HTTPException

from lifeos.wiki_links import resolve_wiki_link


def test_resolver_encodes_verified_silverbullet_link(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    path = wiki / "01-Projects/Mixed Case/Index.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Mixed Case\n", encoding="utf-8")

    result = resolve_wiki_link(
        "01-Projects/Mixed Case/Index.md",
        wiki,
        silverbullet_base_url="https://silverbullet.example.test",
    )

    assert result == {
        "path": "01-Projects/Mixed Case/Index.md",
        "available": True,
        "link_status": "valid",
        "canonical_url": "https://silverbullet.example.test/01-Projects/Mixed%20Case/Index",
        "diagnostic": None,
    }


def test_resolver_returns_internal_preview_when_external_url_is_not_configured(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    path = wiki / "02-Areas/House/index.md"
    path.parent.mkdir(parents=True)
    path.write_text("# House\n", encoding="utf-8")

    result = resolve_wiki_link("02-Areas/House/index.md", wiki)

    assert result["canonical_url"] == "/sources/wiki/02-Areas/House/index.md"
    assert result["link_status"] == "valid"


def test_resolver_reports_missing_source_instead_of_emitting_dead_anchor(tmp_path: Path) -> None:
    result = resolve_wiki_link("01-Projects/Missing/index.md", tmp_path / "wiki")

    assert result["available"] is False
    assert result["canonical_url"] is None
    assert result["link_status"] == "missing"
    assert result["diagnostic"] == "Canonical wiki source is missing"


def test_resolver_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(HTTPException, match="escapes wiki root"):
        resolve_wiki_link("../secret.md", tmp_path / "wiki")
