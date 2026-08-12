from pathlib import Path

from scripts.validate_wiki_links import validate_wiki_links


def test_validator_reports_valid_missing_ambiguous_and_traversal_links(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    valid = wiki / "01-Projects/Valid/Index.md"
    ambiguous_md = wiki / "02-Areas/Ambiguous.md"
    ambiguous_index = wiki / "02-Areas/Ambiguous/index.md"
    for path in (valid, ambiguous_md, ambiguous_index):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n", encoding="utf-8")
    (wiki / "01-Projects/index.md").write_text(
        "# Projects\n\n"
        "- [[01-Projects/Valid/Index|Valid]]\n"
        "- [[01-Projects/Missing|Missing]]\n"
        "- [[../outside|Traversal]]\n",
        encoding="utf-8",
    )
    (wiki / "02-Areas/index.md").write_text(
        "# Areas\n\n- [[02-Areas/Ambiguous|Ambiguous]]\n",
        encoding="utf-8",
    )

    report = validate_wiki_links(wiki)

    assert report["checked_links"] == 4
    assert report["valid_links"] == 1
    assert report["valid"] is False
    assert [item["status"] for item in report["errors"]] == ["missing", "traversal", "ambiguous"]


def test_validator_accepts_mixed_case_index_paths(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    project = wiki / "01-Projects/Demo/Index.md"
    area = wiki / "02-Areas/House/index.md"
    project.parent.mkdir(parents=True)
    area.parent.mkdir(parents=True)
    project.write_text("# Demo\n", encoding="utf-8")
    area.write_text("# House\n", encoding="utf-8")
    (wiki / "01-Projects/index.md").write_text("- [[01-Projects/Demo/index|Demo]]\n", encoding="utf-8")
    (wiki / "02-Areas/index.md").write_text("- [[02-Areas/House/Index|House]]\n", encoding="utf-8")

    report = validate_wiki_links(wiki)

    assert report == {"valid": True, "checked_links": 2, "valid_links": 2, "errors": []}
