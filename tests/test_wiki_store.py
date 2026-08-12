from pathlib import Path

from lifeos.wiki_store import WikiRepository, parse_frontmatter, render_frontmatter


def test_frontmatter_round_trip_preserves_structured_values() -> None:
    text = render_frontmatter({"id": "prj-demo", "type": "project", "tags": ["one", "two"]}, "# Demo\n\nKeep this prose.")
    fields, body = parse_frontmatter(text)
    assert fields["id"] == "prj-demo"
    assert fields["tags"] == ["one", "two"]
    assert "Keep this prose." in body


def test_repository_creates_and_updates_one_project_without_duplicate(tmp_path: Path) -> None:
    repo = WikiRepository(tmp_path / "wiki")
    first = repo.write("project", "Demo Project", {"status": "active"})
    second = repo.write("project", "Demo Project", {"id": first.record_id, "status": "paused"})
    assert first.path == second.path
    assert len(repo.list_records("project")) == 1
    assert repo.read(second.path).fields["status"] == "paused"


def test_repository_discovers_legacy_project_index(tmp_path: Path) -> None:
    path = tmp_path / "wiki/01-Projects/Legacy/Index.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Legacy\n\nExisting project.\n", encoding="utf-8")
    records = WikiRepository(tmp_path / "wiki").list_records("project")
    assert records[0].title == "Legacy"
    assert records[0].path.endswith("Index.md")
