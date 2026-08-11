from fastapi.testclient import TestClient

from lifeos.main import create_app


def test_source_resolution_is_bounded_and_read_only(tmp_path, monkeypatch) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "note.md").write_text("private note")
    monkeypatch.setenv("LIFEOS_WIKI_ROOT", str(wiki))
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}", auth_username="brian", auth_password="password"
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})

    content = client.get("/api/sources/wiki/content", params={"path": "note.md"})
    assert content.status_code == 200
    assert content.json()["content"] == "private note"
    listing = client.get("/api/sources/wiki/list", params={"prefix": "", "limit": 10})
    assert listing.status_code == 200
    assert listing.json()[0]["path"] == "note.md"
    assert client.get("/api/sources/wiki/content", params={"path": "missing.md"}).json()["available"] is False
    assert client.get("/api/sources/wiki/list", params={"prefix": "../"}).status_code == 400
    assert client.get("/api/sources/wiki/content", params={"path": "../secret"}).status_code == 400
