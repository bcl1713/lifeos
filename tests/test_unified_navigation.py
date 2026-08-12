from pathlib import Path

from fastapi.testclient import TestClient

from lifeos.main import create_app


def _canonical_wiki(root: Path) -> None:
    project = root / "01-Projects/Demo Project/Index.md"
    area = root / "02-Areas/House/index.md"
    project.parent.mkdir(parents=True)
    area.parent.mkdir(parents=True)
    project.write_text(
        "---\nid: prj-demo\ntype: project\nstatus: active\nsummary: Canonical demo\n---\n# Demo Project\n",
        encoding="utf-8",
    )
    area.write_text(
        "---\nid: area-house\ntype: area\nstatus: active\nsummary: Home operations\n---\n# House\n",
        encoding="utf-8",
    )
    (root / "01-Projects/index.md").write_text(
        "# Projects\n\n- [[01-Projects/Demo Project/Index|Demo Project]]\n", encoding="utf-8"
    )
    (root / "02-Areas/index.md").write_text("# Areas\n\n- [[02-Areas/House/index|House]]\n", encoding="utf-8")


def test_primary_navigation_has_one_project_surface_and_no_wiki_surface(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    _canonical_wiki(wiki)
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app, follow_redirects=False)
    client.post("/login", data={"username": "brian", "password": "password"})

    projects = client.get("/projects")
    areas = client.get("/areas")
    old_context = client.get("/context")

    assert projects.status_code == 200
    assert projects.text.count('href="/projects"') == 1
    assert 'href="/context"' not in projects.text
    assert ">Wiki<" not in projects.text
    assert "Demo Project" in projects.text
    assert "Canonical demo" in projects.text
    assert "/sources/wiki/01-Projects/Demo%20Project/Index.md" in projects.text
    assert areas.status_code == 200
    assert "House" in areas.text
    assert "Home operations" in areas.text
    assert old_context.status_code == 308
    assert old_context.headers["location"] == "/projects"


def test_projects_view_ignores_projection_only_project(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    _canonical_wiki(wiki)
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    from lifeos.domain import Project

    with app.state.session_factory() as session:
        session.add(Project(title="Projection-only ghost"))
        session.commit()
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})

    response = client.get("/projects")

    assert "Demo Project" in response.text
    assert "Projection-only ghost" not in response.text


def test_project_and_area_detail_routes_resolve_current_canonical_source_and_related_records(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    _canonical_wiki(wiki)
    task = wiki / "01-Projects/LifeOS/lifeos/tasks/demo-task.md"
    task.parent.mkdir(parents=True)
    task.write_text(
        "---\nid: tsk-demo\ntype: task\ntitle: Demo task\nstatus: open\n"
        "project_wiki_id: prj-demo\narea_wiki_id: area-house\n---\n# Demo task\n",
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

    project = client.get("/projects/prj-demo")
    area = client.get("/areas/area-house")

    assert project.status_code == 200
    assert "Demo Project" in project.text
    assert "prj-demo" in project.text
    assert "Demo task" in project.text
    assert "/sources/wiki/01-Projects/Demo%20Project/Index.md" in project.text
    assert area.status_code == 200
    assert "House" in area.text
    assert "area-house" in area.text
    assert "Demo task" in area.text
    assert client.get("/projects/area-house").status_code == 404
