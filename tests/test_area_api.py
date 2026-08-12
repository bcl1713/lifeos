from pathlib import Path

from fastapi.testclient import TestClient

from lifeos.main import create_app


def test_area_api_creates_and_updates_canonical_wiki_record(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    created = client.post("/api/areas", json={"title": "House", "aliases": ["Home"], "summary": "Home operations"})
    assert created.status_code == 201
    area = created.json()
    assert area["id"].startswith("area-")
    path = wiki / area["wiki_path"]
    assert path.exists()
    assert "Home operations" in path.read_text(encoding="utf-8")
    updated = client.patch(f"/api/areas/{area['id']}", json={"status": "paused", "summary": "Updated house operations"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "paused"
    assert "Updated house operations" in path.read_text(encoding="utf-8")
    assert client.get("/api/areas").json()[0]["id"] == area["id"]


def test_area_update_rejects_stale_wiki_hash(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(database_url=f"sqlite:///{tmp_path / 'lifeos.db'}", auth_username="brian", auth_password="password", scheduler_enabled=False, wiki_root=str(wiki))
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    area = client.post("/api/areas", json={"title": "House"}).json()
    path = wiki / area["wiki_path"]
    path.write_text(path.read_text(encoding="utf-8") + "\nExternal edit.\n", encoding="utf-8")
    response = client.patch(f"/api/areas/{area['id']}", json={"status": "paused", "expected_hash": area["wiki_hash"]})
    assert response.status_code == 409


def test_area_api_requires_wiki_configuration(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    assert client.get("/api/areas").status_code == 503
