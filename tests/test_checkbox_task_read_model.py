from pathlib import Path

from fastapi.testclient import TestClient

from lifeos.main import create_app


def _client(tmp_path: Path, wiki: Path) -> TestClient:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'projection.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    return client


def _write_wiki(wiki: Path) -> None:
    source = wiki / "01-Projects" / "Alpha" / "index.md"
    task = wiki / "01-Projects" / "Alpha" / "lifeos" / "tasks" / "linked.md"
    task.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            (
                "- [x] Completed first",
                "- [ ] [Linked second](lifeos/tasks/linked.md)",
                "- [ ] Plain third",
            )
        ),
        encoding="utf-8",
    )
    task.write_text(
        (
            "---\nid: tsk-linked\ntype: task\ntitle: Linked record\npriority: 2\nstatus: completed"
            "\n---\n## Summary\n\nLinked metadata\n"
        ),
        encoding="utf-8",
    )


def test_versioned_checkbox_read_api_is_authenticated_scanner_authoritative_and_filters_deterministically(
    tmp_path: Path,
) -> None:
    wiki = tmp_path / "wiki"
    _write_wiki(wiki)
    unauthenticated = TestClient(
        create_app(database_url=f"sqlite:///{tmp_path / 'empty.db'}", scheduler_enabled=False, wiki_root=str(wiki))
    )
    assert unauthenticated.get("/api/v1/checkbox-tasks").status_code == 401

    client = _client(tmp_path, wiki)

    response = client.get("/api/v1/checkbox-tasks")

    assert response.status_code == 200
    payload = response.json()
    assert [task["label"] for task in payload["tasks"]] == ["Completed first", "Linked second", "Plain third"]
    assert [task["source"]["line"] for task in payload["tasks"]] == [1, 2, 3]
    assert payload["tasks"][0]["checked"] is True
    linked = payload["tasks"][1]
    assert linked["source"] == {
        "path": "01-Projects/Alpha/index.md",
        "line": 2,
        "column": 1,
        "excerpt": "- [ ] [Linked second](lifeos/tasks/linked.md)",
        "url": "/sources/wiki/01-Projects/Alpha/index.md",
        "diagnostic": None,
    }
    assert linked["linked_record"] == {
        "id": "tsk-linked",
        "title": "Linked record",
        "summary": "Linked metadata",
        "priority": 2,
        "path": "01-Projects/Alpha/lifeos/tasks/linked.md",
        "url": "/sources/wiki/01-Projects/Alpha/lifeos/tasks/linked.md",
        "diagnostic": None,
    }
    assert payload["diagnostics"][0]["code"] == "CHECKBOX_STATUS_DISAGREEMENT"
    assert payload["policy"]["allowed_roots"] == ["01-Projects", "02-Areas", "dailies"]

    open_tasks = client.get("/api/v1/checkbox-tasks", params={"state": "open"}).json()["tasks"]
    checked_tasks = client.get("/api/v1/checkbox-tasks", params={"state": "checked"}).json()["tasks"]
    assert [task["label"] for task in open_tasks] == ["Linked second", "Plain third"]
    assert [task["label"] for task in checked_tasks] == ["Completed first"]


def test_today_and_tasks_render_checkbox_observations_without_projection_rows_or_write_controls(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    _write_wiki(wiki)
    client = _client(tmp_path, wiki)

    for path in ("/", "/tasks"):
        page = client.get(path)
        assert page.status_code == 200
        assert "Linked second" in page.text
        if path == "/tasks":
            assert "Checked" in page.text
        else:
            assert "Completed first" not in page.text
        assert "01-Projects/Alpha/index.md:2:1" in page.text
        assert "Open checklist source" in page.text
        assert "Open linked task record" in page.text
        assert "/ui/tasks/" not in page.text
        assert "Checkbox state is read-only in LifeOS" in page.text


def test_unsafe_link_is_not_clickable_and_is_reported_in_api_and_html(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source = wiki / "01-Projects" / "Alpha" / "index.md"
    source.parent.mkdir(parents=True)
    source.write_text("- [ ] [Unsafe](../../outside.md)\n", encoding="utf-8")
    client = _client(tmp_path, wiki)

    payload = client.get("/api/v1/checkbox-tasks").json()
    assert payload["tasks"][0]["linked_record"] is None
    assert payload["diagnostics"][0]["code"] == "UNSAFE_TASK_LINK"
    assert payload["diagnostics"][0]["link_destination"] is None

    page = client.get("/tasks")
    assert "UNSAFE_TASK_LINK" in page.text
    assert "Open linked task record" not in page.text
    assert 'href="../../outside.md"' not in page.text
