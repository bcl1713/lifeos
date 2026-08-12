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
