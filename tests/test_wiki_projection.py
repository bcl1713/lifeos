from pathlib import Path

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import Project
from lifeos.scripts_bridge import sync_wiki_projection
from lifeos.wiki_store import WikiRepository


def test_wiki_edit_rebuilds_project_projection(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    path = wiki / "01-Projects/example/index.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\nid: prj-example\ntype: project\nstatus: active\nowner: Brian\n---\n# Example\n\nA canonical project.\n",
        encoding="utf-8",
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'lifeos.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)
    repo = WikiRepository(wiki)
    with factory() as session:
        result = sync_wiki_projection(session, repo)
        assert result["created"] == 1
        project = session.query(Project).one()
        assert project.wiki_id == "prj-example"
        assert project.owner == "Brian"
    path.write_text(
        "---\nid: prj-example\ntype: project\nstatus: paused\nowner: Brian\n---\n# Example\n\nUpdated.\n",
        encoding="utf-8",
    )
    with factory() as session:
        result = sync_wiki_projection(session, repo)
        assert result["updated"] == 1
        assert session.query(Project).one().status == "paused"
