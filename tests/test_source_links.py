from pathlib import Path

from fastapi.testclient import TestClient

from lifeos.main import create_app


def test_authenticated_internal_wiki_source_route_renders_canonical_markdown(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    note = wiki / "01-Projects/Mixed Case/Index.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Mixed Case\n\nCanonical content.\n", encoding="utf-8")
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)

    assert client.get("/sources/wiki/01-Projects/Mixed%20Case/Index.md").status_code == 401
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    response = client.get("/sources/wiki/01-Projects/Mixed%20Case/Index.md")

    assert response.status_code == 200
    assert "Mixed Case" in response.text
    assert "Canonical content." in response.text
    assert "01-Projects/Mixed Case/Index.md" in response.text


def test_rendered_source_uses_shared_reading_shell_and_selectable_copyable_path(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    note = wiki / "02-Areas/House/Index.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "# House\n\n## Notes\n\n- one\n- two\n\n`inline`\n\n```text\nlong unbroken code sample\n```\n",
        encoding="utf-8",
    )
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})

    response = client.get("/sources/wiki/02-Areas/House/Index.md")

    assert response.status_code == 200
    assert '<header>' in response.text
    assert 'href="/areas"' in response.text
    assert '<nav aria-label="Source context">' in response.text
    assert 'href="/areas">Areas</a>' in response.text
    assert "Canonical Markdown" in response.text
    assert "read-only" in response.text
    assert '<code class="source-path" id="source-path">02-Areas/House/Index.md</code>' in response.text
    assert '<button type="button" class="copy-path"' in response.text
    assert 'data-copy-path aria-describedby="copy-path-status" hidden>Copy path</button>' in response.text
    assert 'button.hidden = false;' in response.text
    assert 'aria-live="polite"' in response.text
    assert '<article class="markdown-body">' in response.text
    assert 'class="source-page"' in response.text


def test_source_api_uses_configured_app_wiki_root(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    note = wiki / "02-Areas/House/index.md"
    note.parent.mkdir(parents=True)
    note.write_text("# House\n", encoding="utf-8")
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})

    response = client.get("/api/sources/wiki", params={"path": "02-Areas/House/index.md"})

    assert response.status_code == 200
    assert response.json()["canonical_url"] == "/sources/wiki/02-Areas/House/index.md"
    assert response.json()["link_status"] == "valid"


def test_rendered_source_keeps_relative_markdown_navigation_internal_and_diagnoses_unsafe_targets(
    tmp_path: Path,
) -> None:
    wiki = tmp_path / "wiki"
    note = wiki / "01-Projects/Demo/Index.md"
    sibling = note.parent / "Sibling.md"
    note.parent.mkdir(parents=True)
    sibling.write_text("# Sibling\n", encoding="utf-8")
    (wiki / "01-Projects/One").mkdir()
    (wiki / "01-Projects/Two").mkdir()
    (wiki / "01-Projects/One/Duplicate.md").write_text("# One\n", encoding="utf-8")
    (wiki / "01-Projects/Two/Duplicate.md").write_text("# Two\n", encoding="utf-8")
    note.write_text(
        "# Demo\n\n[Sibling](Sibling.md) [[Missing]] [[Duplicate]] [[../secret]] [Asset](asset.pdf) "
        "[Unsafe](javascript:alert(1))\n",
        encoding="utf-8",
    )
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})

    response = client.get("/sources/wiki/01-Projects/Demo/Index.md")

    assert '<a href="/sources/wiki/01-Projects/Demo/Sibling.md">Sibling</a>' in response.text
    assert "Missing wiki link target: Missing" in response.text
    assert "Ambiguous wiki link target: Duplicate" in response.text
    assert "Wiki link escapes wiki root" in response.text
    assert "Wiki link target is not Markdown" in response.text
    assert "Unsafe link scheme" in response.text
    assert 'href="javascript:' not in response.text


def test_source_route_rejects_symlinked_canonical_note(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    target = wiki / "target.md"
    target.write_text("# Target\n", encoding="utf-8")
    (wiki / "unsafe.md").symlink_to(target)
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})

    response = client.get("/sources/wiki/unsafe.md")

    assert response.status_code == 404
    assert response.json()["detail"] == "Canonical wiki source is symlink-unsafe"
