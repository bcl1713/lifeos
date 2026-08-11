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

    assert client.get("/api/sources/wiki", params={"path": "note.md"}).json()["available"] is True
    assert client.get("/api/sources/wiki", params={"path": "missing.md"}).json()["available"] is False
    traversal = client.get("/api/sources/wiki", params={"path": "../secret"})
    assert traversal.status_code == 400
