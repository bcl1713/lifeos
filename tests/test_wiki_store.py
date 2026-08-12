from pathlib import Path
import stat

from lifeos.wiki_store import WikiRepository, parse_frontmatter, render_frontmatter


def test_frontmatter_round_trip_preserves_structured_values() -> None:
    text = render_frontmatter({"id": "prj-demo", "type": "project", "tags": ["one", "two"]}, "# Demo\n\nKeep this prose.")
    fields, body = parse_frontmatter(text)
    assert fields["id"] == "prj-demo"
    assert fields["tags"] == ["one", "two"]
    assert "Keep this prose." in body


def test_frontmatter_round_trip_preserves_null_empty_boolean_and_multiline_strings() -> None:
    values = {
        "missing": None,
        "empty": "",
        "enabled": True,
        "notes": "First line\nSecond line",
    }
    fields, _body = parse_frontmatter(render_frontmatter(values, "# Demo"))
    assert fields == values


def test_frontmatter_normalizes_yaml_surrogate_pairs_to_unicode_scalars() -> None:
    fields, _body = parse_frontmatter('---\nnotes: "Subject \\uD83D\\uDC8C"\n---\n\n# Demo\n')

    assert fields["notes"] == "Subject 💌"
    assert fields["notes"].encode("utf-8") == b"Subject \xf0\x9f\x92\x8c"


def test_repository_creates_and_updates_one_project_without_duplicate(tmp_path: Path) -> None:
    repo = WikiRepository(tmp_path / "wiki")
    first = repo.write("project", "Demo Project", {"status": "active"})
    second = repo.write("project", "Demo Project", {"id": first.record_id, "status": "paused"})
    assert first.path == second.path
    assert len(repo.list_records("project")) == 1
    assert repo.read(second.path).fields["status"] == "paused"


def test_repository_update_preserves_unknown_yaml_structures_and_comments(tmp_path: Path) -> None:
    path = tmp_path / "wiki/01-Projects/Demo/Index.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "id: prj-demo\n"
        "type: project\n"
        "title: Demo\n"
        "status: active # keep status comment\n"
        "aliases:\n"
        "  - One\n"
        "  - Two\n"
        "custom:\n"
        "  owner:\n"
        "    name: Brian\n"
        "  notes: |\n"
        "    First line\n"
        "    Second line\n"
        "---\n"
        "# Demo\n\nKeep prose.\n",
        encoding="utf-8",
    )
    (tmp_path / "wiki/01-Projects/index.md").write_text(
        "- [[01-Projects/Demo/Index|Demo]]\n",
        encoding="utf-8",
    )
    repository = WikiRepository(tmp_path / "wiki")
    before = repository.read("01-Projects/Demo/Index.md")

    repository.write(
        "project",
        "Demo",
        {"status": "paused"},
        path=before.path,
        expected_hash=before.content_hash,
    )

    text = path.read_text(encoding="utf-8")
    updated = repository.read("01-Projects/Demo/Index.md")
    assert "# keep status comment" in text
    assert updated.fields["aliases"] == ["One", "Two"]
    assert updated.fields["custom"]["owner"]["name"] == "Brian"
    assert updated.fields["custom"]["notes"] == "First line\nSecond line\n"
    assert updated.fields["status"] == "paused"
    assert "Keep prose." in updated.body


def test_repository_reads_and_repairs_legacy_unquoted_colon_scalar(tmp_path: Path) -> None:
    path = tmp_path / "wiki/01-Projects/LifeOS/lifeos/tasks/imported.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "id: tsk-imported\n"
        "type: task\n"
        "title: Imported\n"
        "notes: Source: google-tasks:legacy-id\n"
        "status: open\n"
        "---\n"
        "# Imported\n",
        encoding="utf-8",
    )
    repository = WikiRepository(tmp_path / "wiki")

    before = repository.read("01-Projects/LifeOS/lifeos/tasks/imported.md")
    assert before.fields["notes"] == "Source: google-tasks:legacy-id"
    repository.write(
        "task",
        "Imported",
        {"status": "completed"},
        path=before.path,
        expected_hash=before.content_hash,
    )

    text = path.read_text(encoding="utf-8")
    assert 'notes: "Source: google-tasks:legacy-id"' in text
    assert repository.read(before.path).fields["status"] == "completed"


def test_same_title_projects_use_distinct_canonical_paths(tmp_path: Path) -> None:
    repository = WikiRepository(tmp_path / "wiki")
    first = repository.write("project", "Duplicate", {"id": "prj-duplicate"})
    second = repository.write("project", "Duplicate", {"id": "prj-duplicate-second"})

    assert first.path != second.path
    assert repository.find_by_id(first.record_id).path == first.path
    assert repository.find_by_id(second.record_id).path == second.path


def test_create_does_not_claim_untyped_legacy_project_path(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    legacy = root / "01-Projects/duplicate/index.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# Duplicate\n\nLegacy project prose.\n", encoding="utf-8")
    (root / "01-Projects/index.md").write_text(
        "- [[01-Projects/duplicate/index|Duplicate]]\n", encoding="utf-8"
    )
    repository = WikiRepository(root)

    created = repository.write("project", "Duplicate", {"id": "prj-duplicate-new"})

    assert created.path != "01-Projects/duplicate/index.md"
    assert legacy.read_text(encoding="utf-8") == "# Duplicate\n\nLegacy project prose.\n"
    assert repository.find_by_id("prj-duplicate").path == "01-Projects/duplicate/index.md"
    assert repository.find_by_id("prj-duplicate-new").path == created.path


def test_atomic_update_preserves_existing_file_mode(tmp_path: Path) -> None:
    repository = WikiRepository(tmp_path / "wiki")
    record = repository.write("task", "Mode", {"id": "tsk-mode", "status": "open"})
    path = tmp_path / "wiki" / record.path
    path.chmod(0o664)
    current = repository.read(record.path)

    repository.write(
        "task",
        "Mode",
        {"status": "completed"},
        path=record.path,
        expected_hash=current.content_hash,
    )

    assert stat.S_IMODE(path.stat().st_mode) == 0o664


def test_repository_discovers_indexed_legacy_project_with_mixed_case_filename(tmp_path: Path) -> None:
    path = tmp_path / "wiki/01-Projects/Legacy/Index.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Legacy\n\nExisting project.\n", encoding="utf-8")
    index = tmp_path / "wiki/01-Projects/index.md"
    index.write_text("# Projects\n\n- [[01-Projects/Legacy/Index|Legacy]]\n", encoding="utf-8")
    records = WikiRepository(tmp_path / "wiki").list_records("project")
    assert records[0].title == "Legacy"
    assert records[0].path.endswith("Index.md")
