from pathlib import Path

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.scripts_bridge import reconcile_wiki_projection, sync_wiki_projection
from lifeos.wiki_store import WikiRepository


def test_reconciliation_reports_missing_orphaned_and_hash_conflicts(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    repository = WikiRepository(wiki)
    project = repository.write("project", "Canonical Project", {"status": "active"}, "# Canonical Project\n")
    engine = create_engine(f"sqlite:///{tmp_path / 'lifeos.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        sync_wiki_projection(session, repository)
        assert reconcile_wiki_projection(session, repository)["aligned"] is True
        path = wiki / project.path
        path.write_text(path.read_text(encoding="utf-8") + "\nExternal edit.\n", encoding="utf-8")
        report = reconcile_wiki_projection(session, repository)
        assert report["hash_conflicts"] == [project.record_id]
        assert report["aligned"] is False
