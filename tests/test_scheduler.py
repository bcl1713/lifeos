import time
from pathlib import Path

from fastapi.testclient import TestClient

from lifeos.main import create_app


def test_scheduler_reconciles_checkbox_observations_without_writing_source_or_projection(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source = wiki / "dailies" / "today.md"
    source.parent.mkdir(parents=True)
    source.write_text("- [ ] observe\n", encoding="utf-8")
    database = tmp_path / "lifeos.db"
    app = create_app(
        database_url=f"sqlite:///{database}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=True,
        scheduler_interval_seconds=60,
        checkbox_refresh_interval_seconds=0.01,
        checkbox_watcher_enabled=False,
        wiki_root=str(wiki),
    )
    source_before = source.read_bytes()
    database_before = database.read_bytes()

    with TestClient(app):
        deadline = time.monotonic() + 1
        while app.state.checkbox_refresh_coordinator.last_result is None and time.monotonic() < deadline:
            time.sleep(0.01)
        result = app.state.checkbox_refresh_coordinator.last_result
        assert result is not None
        assert [task.label for task in result.tasks] == ["observe"]
        assert app.state.checkbox_refresh_watcher.diagnostic == "disabled"

    assert source.read_bytes() == source_before
    assert database.read_bytes() == database_before
