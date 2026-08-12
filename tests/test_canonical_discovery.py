from pathlib import Path
import os

from lifeos.wiki_store import WikiRepository


def test_project_and_area_discovery_follows_canonical_indexes_only(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    canonical_project = wiki / "01-Projects/Demo/Index.md"
    nested_project = wiki / "01-Projects/Demo/trips/index.md"
    canonical_area = wiki / "02-Areas/House/index.md"
    nested_area = wiki / "02-Areas/House/audits/index.md"
    for path in (canonical_project, nested_project, canonical_area, nested_area):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.parent.name}\n", encoding="utf-8")
    (wiki / "01-Projects/index.md").write_text("# Projects\n\n- [[01-Projects/Demo/Index|Demo]]\n", encoding="utf-8")
    (wiki / "02-Areas/index.md").write_text("# Areas\n\n- [[02-Areas/House/index|House]]\n", encoding="utf-8")

    repository = WikiRepository(wiki)

    assert [record.path for record in repository.list_records("project")] == ["01-Projects/Demo/Index.md"]
    assert [record.path for record in repository.list_records("area")] == ["02-Areas/House/index.md"]
    assert repository.list_records("project")[0].record_id == "prj-demo"
    assert repository.list_records("area")[0].record_id == "area-house"


def test_indexed_discovery_resolves_final_markdown_filename_case(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    project = wiki / "01-Projects/ChoreQuest/index.md"
    project.parent.mkdir(parents=True)
    project.write_text("---\nid: chorequest\ntype: project\ntitle: ChoreQuest\n---\n# ChoreQuest\n", encoding="utf-8")
    (wiki / "01-Projects/index.md").write_text(
        "# Projects\n\n- [[01-Projects/ChoreQuest/Index|ChoreQuest]]\n",
        encoding="utf-8",
    )

    records = WikiRepository(wiki).list_records("project")

    assert [(record.record_id, record.path) for record in records] == [
        ("chorequest", "01-Projects/ChoreQuest/index.md")
    ]


def test_typed_discovery_excludes_templates_and_untyped_notes(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    task = wiki / "01-Projects/LifeOS/lifeos/tasks/do-it.md"
    template = wiki / "templates/task-note.md"
    ordinary = wiki / "03-Research/random.md"
    for path in (task, template, ordinary):
        path.parent.mkdir(parents=True, exist_ok=True)
    task.write_text("---\nid: tsk-do-it\ntype: task\n---\n# Do it\n", encoding="utf-8")
    template.write_text("---\nid: '{{id}}'\ntype: task\n---\n# Template\n", encoding="utf-8")
    ordinary.write_text("# Ordinary\n", encoding="utf-8")

    records = WikiRepository(wiki).list_records("task")

    assert [record.record_id for record in records] == ["tsk-do-it"]


def test_discovery_deduplicates_case_aliases_of_the_same_physical_file(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    canonical = wiki / "01-Projects/Demo/Index.md"
    alias = wiki / "01-Projects/Demo/index.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("---\nid: prj-demo\ntype: project\n---\n# Demo\n", encoding="utf-8")
    os.link(canonical, alias)
    (wiki / "01-Projects/index.md").write_text(
        "# Projects\n\n- [[01-Projects/Demo/Index|Demo]]\n",
        encoding="utf-8",
    )

    records = WikiRepository(wiki).list_records()

    assert [(record.record_id, record.path) for record in records] == [("prj-demo", "01-Projects/Demo/Index.md")]


def test_new_project_is_registered_once_in_canonical_index(tmp_path: Path) -> None:
    repository = WikiRepository(tmp_path / "wiki")

    first = repository.write("project", "Demo Project", {"id": "prj-demo", "status": "active"})
    repository.write("project", "Demo Project", {"id": "prj-demo", "status": "paused"}, path=first.path)

    index = (repository.root / "01-Projects/index.md").read_text(encoding="utf-8")
    assert index.count("[[01-Projects/demo-project/index|Demo Project]]") == 1


def test_repository_write_uses_atomic_replace(tmp_path: Path, monkeypatch) -> None:
    repository = WikiRepository(tmp_path / "wiki")
    replaced: list[tuple[str, str]] = []
    original_replace = Path.replace

    def tracked_replace(source: Path, target: Path):
        replaced.append((source.name, target.name))
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", tracked_replace)
    record = repository.write("task", "Atomic", {"id": "tsk-atomic", "status": "open"})

    assert replaced
    assert replaced[-1][1] == Path(record.path).name
    assert (repository.root / record.path).is_file()
