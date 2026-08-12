from pathlib import Path

from scripts.validate_authority_docs import validate_authority_docs


def test_repository_documentation_declares_one_canonical_wiki_authority() -> None:
    repository = Path(__file__).resolve().parents[1]

    result = validate_authority_docs(repository)

    assert result["valid"] is True, result["errors"]
    assert result["checked_documents"] == 3


def test_validator_rejects_sqlite_domain_authority_and_missing_source_first_contract(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text(
        "Tasks and projects have SQLite-backed CRUD APIs. Active task state is authoritative in LifeOS.\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/architecture.md").write_text("SQLite is the system of record.\n", encoding="utf-8")
    (tmp_path / "docs/operations.md").write_text("LifeOS owns durable tasks.\n", encoding="utf-8")

    result = validate_authority_docs(tmp_path)

    assert result["valid"] is False
    assert any("forbidden authority claim" in error for error in result["errors"])
    assert any("source-first" in error for error in result["errors"])
