from pathlib import Path

from fastapi.testclient import TestClient

from lifeos.main import create_app


def _write_record(path: Path, *, record_id: str, record_type: str, title: str, status: str, aliases: str = "[]") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {record_id}\ntype: {record_type}\ntitle: {title}\nstatus: {status}\naliases: {aliases}\n---\n# {title}\n",
        encoding="utf-8",
    )


def test_project_and_area_views_search_alias_path_and_filter_status(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    _write_record(
        wiki / "01-Projects/Alpha Launch/Index.md",
        record_id="prj-alpha",
        record_type="project",
        title="Alpha Launch",
        status="active",
        aliases='["Apollo"]',
    )
    _write_record(
        wiki / "01-Projects/Closed Work/index.md",
        record_id="prj-closed",
        record_type="project",
        title="Closed Work",
        status="archived",
    )
    _write_record(
        wiki / "02-Areas/House/index.md",
        record_id="area-house",
        record_type="area",
        title="House",
        status="active",
        aliases='["Home"]',
    )
    (wiki / "01-Projects/index.md").write_text(
        "# Projects\n\n- [[01-Projects/Alpha Launch/Index|Alpha]]\n- [[01-Projects/Closed Work/index|Closed]]\n",
        encoding="utf-8",
    )
    (wiki / "02-Areas/index.md").write_text("# Areas\n\n- [[02-Areas/House/index|House]]\n", encoding="utf-8")
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})

    by_alias = client.get("/projects?q=apollo")
    by_path = client.get("/projects?q=closed%20work")
    active = client.get("/projects?status=active")
    archived = client.get("/projects?status=archived")
    area_alias = client.get("/areas?q=home")

    assert "Alpha Launch" in by_alias.text and "Closed Work" not in by_alias.text
    assert "Closed Work" in by_path.text and "Alpha Launch" not in by_path.text
    assert "Alpha Launch" in active.text and "Closed Work" not in active.text
    assert "Closed Work" in archived.text and "Alpha Launch" not in archived.text
    assert "House" in area_alias.text
    assert 'name="q"' in active.text
    assert 'name="status"' in active.text
