from pathlib import Path

from fastapi.testclient import TestClient

from lifeos.main import create_app
from scripts.sync_wiki_context import sync_wiki_context


def make_wiki(root: Path) -> None:
    (root / "01-Projects/demo").mkdir(parents=True)
    (root / "02-Areas/house").mkdir(parents=True)
    (root / "01-Projects/demo/index.md").write_text(
        "---\nid: demo-project\naliases: [Demo]\nstatus: active\n---\n# Demo Project\n\nA project summary.\n"
    )
    (root / "02-Areas/house/index.md").write_text(
        "---\nid: house-area\naliases:\n  - House\n---\n# House\n\nThe home operating area.\n"
    )
    (root / "01-Projects/legacy").mkdir(parents=True)
    (root / "01-Projects/legacy/Index.md").write_text("# Legacy Project\n\nLegacy summary.\n")
    (root / "01-Projects/index.md").write_text("# Projects\n\n- [[01-Projects/demo/index|Demo]]\n- [[01-Projects/legacy/Index|Legacy]]\n")
    (root / "02-Areas/index.md").write_text("# Areas\n\n- [[02-Areas/house/index|House]]\n")


def test_sync_indexes_projects_and_areas_idempotently_and_marks_stale(tmp_path) -> None:
    wiki = tmp_path / "wiki"
    make_wiki(wiki)
    db = f"sqlite:///{tmp_path / 'lifeos.db'}"

    first = sync_wiki_context(db, wiki)
    assert first == {"created": 3, "updated": 0, "stale": 0, "unchanged": 0}
    second = sync_wiki_context(db, wiki)
    assert second == {"created": 0, "updated": 0, "stale": 0, "unchanged": 3}

    (wiki / "01-Projects/demo/index.md").unlink()
    third = sync_wiki_context(db, wiki)
    assert third["stale"] == 1


def test_wiki_context_api_and_ui_are_read_only_links(tmp_path, monkeypatch) -> None:
    wiki = tmp_path / "wiki"
    make_wiki(wiki)
    monkeypatch.setenv("LIFEOS_WIKI_ROOT", str(wiki))
    db = f"sqlite:///{tmp_path / 'lifeos.db'}"
    sync_wiki_context(db, wiki)
    app = create_app(database_url=db, auth_username="brian", auth_password="password", scheduler_enabled=False)
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204

    response = client.get("/api/wiki-context")
    assert response.status_code == 200
    items = response.json()
    assert {item["source_type"] for item in items} == {"project", "area"}
    assert items[0]["wiki_path"].lower().endswith("index.md")
    assert items[0]["wiki_url"].startswith("/sources/wiki/")
    assert client.get("/context").status_code == 200
    assert "Demo Project" in client.get("/context").text

    assert client.post("/api/wiki-context", json={"title": "Should not be writable"}).status_code == 405
