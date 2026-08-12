from pathlib import Path

from lifeos.db import create_engine, create_session_factory, initialize_database
from lifeos.domain import Task
from lifeos.scripts_bridge import sync_wiki_projection
from lifeos.wiki_store import WikiRepository


def test_wiki_edit_rebuilds_task_projection(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    path = wiki / "01-Projects/example/lifeos/tasks/review.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\nid: tsk-review\ntype: task\nstatus: open\npriority: 2\ndue_date: 2026-08-20\ntags: [focus]\n---\n# Review\n",
        encoding="utf-8",
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'lifeos.db'}")
    initialize_database(engine)
    factory = create_session_factory(engine)
    repo = WikiRepository(wiki)
    with factory() as session:
        result = sync_wiki_projection(session, repo)
        assert result["created"] == 1
        task = session.query(Task).one()
        assert task.wiki_id == "tsk-review"
        assert task.priority == 2
        assert task.due_date.isoformat() == "2026-08-20"
        assert task.tags == '["focus"]'
    path.write_text(
        "---\nid: tsk-review\ntype: task\nstatus: completed\npriority: 2\ndue_date: 2026-08-20\ntags: [focus]\n---\n# Review\n",
        encoding="utf-8",
    )
    with factory() as session:
        result = sync_wiki_projection(session, repo)
        assert result["updated"] == 1
        assert session.query(Task).one().status == "completed"
