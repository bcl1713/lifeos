"""Regression coverage for the projection-independent checkbox scanner CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient

from lifeos.main import create_app

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _fixture_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _write_wiki(root: Path) -> None:
    source = root / "01-Projects" / "Alpha" / "index.md"
    legacy = root / "01-Projects" / "Alpha" / "lifeos" / "tasks" / "legacy.md"
    legacy.parent.mkdir(parents=True)
    source.write_text(
        "- [ ] [Legacy task](lifeos/tasks/legacy.md)\n- [x] Checklist-only observation\n",
        encoding="utf-8",
    )
    legacy.write_text(
        "---\nid: tsk-legacy\ntype: task\ntitle: Legacy task\nstatus: completed\n---\n"
        "## Summary\n\nReadable legacy metadata\n",
        encoding="utf-8",
    )


def test_checkbox_scanner_cli_is_deterministic_read_only_and_reports_legacy_metadata(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    _write_wiki(wiki)
    before = _fixture_bytes(wiki)
    command = [sys.executable, "scripts/scan_wiki_checkbox_tasks.py", "--wiki-root", str(wiki)]

    first = subprocess.run(command, cwd=REPOSITORY_ROOT, check=True, capture_output=True, text=True)
    second = subprocess.run(command, cwd=REPOSITORY_ROOT, check=True, capture_output=True, text=True)

    assert first.stdout == second.stdout
    assert _fixture_bytes(wiki) == before
    report = json.loads(first.stdout)
    assert report == {
        "diagnostics": [
            {
                "code": "CHECKBOX_STATUS_DISAGREEMENT",
                "column": 1,
                "link_destination": "lifeos/tasks/legacy.md",
                "linked_record_path": "01-Projects/Alpha/lifeos/tasks/legacy.md",
                "line": 1,
                "message": (
                    "Checkbox is open but linked task record status is completed; "
                    "checkbox state remains authoritative."
                ),
                "severity": "warning",
                "source_excerpt": "- [ ] [Legacy task](lifeos/tasks/legacy.md)",
                "source_path": "01-Projects/Alpha/index.md",
            }
        ],
        "policy": {
            "allowed_roots": ["01-Projects", "02-Areas", "dailies"],
            "exclusions": ["03-Research", "04-Archives", "assets", "templates"],
        },
        "tasks": [
            {
                "checked": False,
                "content_fingerprint": sha256(
                    b"01-Projects/Alpha/index.md\0- [ ] [Legacy task](lifeos/tasks/legacy.md)"
                ).hexdigest(),
                "identity": "tsk-legacy plus checkbox occurrence locator",
                "label": "Legacy task",
                "linked_task_id": "tsk-legacy",
                "linked_task_path": "01-Projects/Alpha/lifeos/tasks/legacy.md",
                "linked_task_priority": None,
                "linked_task_summary": "Readable legacy metadata",
                "linked_task_title": "Legacy task",
                "source_excerpt": "- [ ] [Legacy task](lifeos/tasks/legacy.md)",
                "source_path": "01-Projects/Alpha/index.md",
                "line": 1,
                "column": 1,
            },
            {
                "checked": True,
                "content_fingerprint": sha256(
                    b"01-Projects/Alpha/index.md\0- [x] Checklist-only observation"
                ).hexdigest(),
                "identity": "plain source-path plus content-fingerprint; read-only",
                "label": "Checklist-only observation",
                "linked_task_id": None,
                "linked_task_path": None,
                "linked_task_priority": None,
                "linked_task_summary": None,
                "linked_task_title": None,
                "source_excerpt": "- [x] Checklist-only observation",
                "source_path": "01-Projects/Alpha/index.md",
                "line": 2,
                "column": 1,
            },
        ],
    }


def test_checkbox_reads_are_identical_after_projection_database_is_removed_and_reinitialized(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    _write_wiki(wiki)
    database = tmp_path / "projection.db"

    def read() -> dict[str, object]:
        app = create_app(
            database_url=f"sqlite:///{database}",
            auth_username="brian",
            auth_password="password",
            scheduler_enabled=False,
            wiki_root=str(wiki),
        )
        with TestClient(app) as client:
            assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
            response = client.get("/api/v1/checkbox-tasks")
            assert response.status_code == 200
            return response.json()

    before = read()
    database.unlink()
    after_missing_projection = read()
    database.unlink()
    after_reinitialized_projection = read()

    assert after_missing_projection == before
    assert after_reinitialized_projection == before
