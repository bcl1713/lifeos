"""Regression coverage for inline checkbox links that are not typed task records."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from lifeos.main import create_app
from lifeos.wiki_checkbox_tasks import scan_checkbox_tasks

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_inline_checkboxes_keep_supporting_links_separate_from_explicit_typed_task_links(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    mission = wiki / "01-Projects" / "Alpha" / "mission" / "work-package.md"
    local_tasks = wiki / "01-Projects" / "Alpha" / "tasks.md"
    source_details = mission.parent / "trips" / "26-15.md"
    typed = mission.parent / "lifeos" / "tasks" / "roster.md"
    for path in (mission, local_tasks, source_details, typed):
        path.parent.mkdir(parents=True, exist_ok=True)
    mission.write_text(
        "\n".join(
            (
                "Mission prose.",
                "- [ ] Populate roster ([source details](trips/26-15.md#key-personnel))",
                "- [x] Review [missing details](trips/missing.md)",
                "- [ ] Unsafe [details](../../outside.md)",
                "- [ ] [Typed roster](task:lifeos/tasks/roster.md)",
                "- [ ] [Missing typed](task:lifeos/tasks/missing.md)",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    local_tasks.write_text("- [ ] Local aggregate observation\n", encoding="utf-8")
    source_details.write_text("# Key personnel\n", encoding="utf-8")
    typed.write_text("---\nid: tsk-roster\ntype: task\ntitle: Typed roster\nstatus: open\n---\n", encoding="utf-8")

    result = scan_checkbox_tasks(wiki)

    assert [(task.source_path, task.line, task.checked) for task in result.tasks] == [
        ("01-Projects/Alpha/mission/work-package.md", 2, False),
        ("01-Projects/Alpha/mission/work-package.md", 3, True),
        ("01-Projects/Alpha/mission/work-package.md", 4, False),
        ("01-Projects/Alpha/mission/work-package.md", 5, False),
        ("01-Projects/Alpha/mission/work-package.md", 6, False),
        ("01-Projects/Alpha/tasks.md", 1, False),
    ]
    assert result.tasks[0].label == "Populate roster ([source details](trips/26-15.md#key-personnel))"
    assert result.tasks[0].linked_task_id is None
    assert result.tasks[0].supporting_links[0].path == "01-Projects/Alpha/mission/trips/26-15.md"
    assert result.tasks[0].supporting_links[0].fragment == "key-personnel"
    assert result.tasks[3].linked_task_id == "tsk-roster"
    assert result.tasks[4].linked_task_id is None
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "SUPPORTING_LINK_MISSING",
        "SUPPORTING_LINK_UNSAFE",
        "MISSING_TASK_RECORD",
    ]

    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'projection.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    payload = client.get("/api/v1/checkbox-tasks").json()
    supporting = payload["tasks"][0]["supporting_links"][0]
    assert supporting["label"] == "source details"
    assert supporting["destination"] == "trips/26-15.md#key-personnel"
    assert supporting["path"] == "01-Projects/Alpha/mission/trips/26-15.md"
    assert supporting["url"] == "/sources/wiki/01-Projects/Alpha/mission/trips/26-15.md#key-personnel"
    assert payload["tasks"][3]["linked_record"]["id"] == "tsk-roster"
    assert "Open supporting link" in client.get("/tasks").text

    command = [sys.executable, "scripts/scan_wiki_checkbox_tasks.py", "--wiki-root", str(wiki)]
    first = subprocess.run(command, cwd=REPOSITORY_ROOT, check=True, capture_output=True, text=True)
    second = subprocess.run(command, cwd=REPOSITORY_ROOT, check=True, capture_output=True, text=True)
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["tasks"][0]["supporting_links"][0]["fragment"] == "key-personnel"


def test_explicit_task_destination_is_the_only_typed_marker_and_wiki_links_are_supporting(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source = wiki / "01-Projects" / "Alpha" / "mission" / "index.md"
    typed = source.parent / "lifeos" / "tasks" / "roster.md"
    brief = source.parent / "brief.md"
    for path in (source, typed, brief):
        path.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "\n".join(
            (
                "- [ ] [legacy](lifeos/tasks/roster.md) [[brief#scope|Project brief]] [details](brief.md#scope)",
                "- [x] [typed](task:lifeos/tasks/roster.md) [[brief]] [details](brief.md)",
                "- [ ] [one](task:lifeos/tasks/roster.md) [two](task:lifeos/tasks/roster.md)",
                "- [ ] [legacy only](lifeos/tasks/roster.md)",
            )
        ),
        encoding="utf-8",
    )
    typed.write_text("---\nid: tsk-roster\ntype: task\ntitle: Roster\nstatus: open\n---\n", encoding="utf-8")
    brief.write_text("# Brief\n", encoding="utf-8")

    result = scan_checkbox_tasks(wiki)

    assert result.tasks[0].linked_task_id is None
    assert [(link.kind, link.link_index, link.destination) for link in result.tasks[0].supporting_links] == [
        ("markdown", 0, "lifeos/tasks/roster.md"),
        ("wiki", 1, "brief#scope|Project brief"),
        ("markdown", 2, "brief.md#scope"),
    ]
    assert result.tasks[1].linked_task_id == "tsk-roster"
    assert [(link.kind, link.link_index) for link in result.tasks[1].supporting_links] == [("wiki", 1), ("markdown", 2)]
    assert result.tasks[2].linked_task_id is None
    assert {diagnostic.code for diagnostic in result.diagnostics} == {
        "CHECKBOX_STATUS_DISAGREEMENT",
        "LEGACY_TYPED_TASK_LINK",
        "TYPED_TASK_LINK_CARDINALITY",
    }


def test_explicit_typed_task_link_decodes_a_percent_encoded_space_once(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source = wiki / "01-Projects" / "Alpha" / "index.md"
    typed = source.parent / "lifeos" / "tasks" / "change brakes.md"
    for path in (source, typed):
        path.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "- [ ] [Change brakes](task:lifeos/tasks/change%20brakes.md)\n",
        encoding="utf-8",
    )
    typed.write_text(
        "---\nid: tsk-change-brakes\ntype: task\ntitle: Change brakes\nstatus: open\n---\n",
        encoding="utf-8",
    )

    result = scan_checkbox_tasks(wiki)

    assert result.tasks[0].linked_task_id == "tsk-change-brakes"
    assert result.tasks[0].linked_task_path == "01-Projects/Alpha/lifeos/tasks/change brakes.md"
    assert result.diagnostics == ()


def test_wiki_supporting_links_preserve_safe_and_unsafe_outcomes_without_typed_inference(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source = wiki / "01-Projects" / "Alpha" / "mission" / "index.md"
    brief = wiki / "01-Projects" / "Alpha" / "brief.md"
    typed = source.parent / "lifeos" / "tasks" / "roster.md"
    for path in (source, brief, typed):
        path.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "\n".join(
            (
                "- [ ] [[01-Projects/Alpha/brief#scope|Project brief]]",
                "- [ ] [[../../outside]]",
                "- [ ] [[lifeos/tasks/roster|Typed-shaped context]]",
            )
        ),
        encoding="utf-8",
    )
    brief.write_text("# Brief\n", encoding="utf-8")
    typed.write_text("---\nid: tsk-roster\ntype: task\n---\n", encoding="utf-8")

    result = scan_checkbox_tasks(wiki)

    assert result.tasks[0].linked_task_id is None
    assert result.tasks[0].supporting_links[0].path == "01-Projects/Alpha/brief.md"
    assert result.tasks[0].supporting_links[0].anchor == "scope"
    assert result.tasks[1].supporting_links[0].classification == "unsafe"
    assert result.tasks[2].linked_task_id is None
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["SUPPORTING_WIKI_LINK_UNSAFE"]


def test_markdown_supporting_link_preserves_query_and_fragment_in_safe_api_action(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source = wiki / "01-Projects" / "Alpha" / "index.md"
    target = source.parent / "brief.md"
    source.parent.mkdir(parents=True)
    source.write_text("- [ ] [Brief](brief.md?view=review#scope)\n", encoding="utf-8")
    target.write_text("# Brief\n", encoding="utf-8")

    client = _client_for_inline_link_test(tmp_path, wiki)

    supporting = client.get("/api/v1/checkbox-tasks").json()["tasks"][0]["supporting_links"][0]
    assert supporting["url"] == "/sources/wiki/01-Projects/Alpha/brief.md?view=review#scope"


def test_non_markdown_supporting_link_has_a_non_fatal_diagnostic(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source = wiki / "01-Projects" / "Alpha" / "index.md"
    source.parent.mkdir(parents=True)
    source.write_text("- [ ] [PDF](brief.pdf)\n", encoding="utf-8")

    result = scan_checkbox_tasks(wiki)

    supporting = result.tasks[0].supporting_links[0]
    assert supporting.classification == "non_markdown"
    assert supporting.path is None
    assert supporting.diagnostic == "Supporting link target is not Markdown."
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["SUPPORTING_LINK_NON_MARKDOWN"]
    assert result.diagnostics[0].severity == "warning"


def test_checkbox_level_cardinality_diagnostic_precedes_same_line_link_diagnostics(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    source = wiki / "01-Projects" / "Alpha" / "index.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "- [ ] [one](task:lifeos/tasks/one.md) [two](task:lifeos/tasks/two.md) [missing](missing.md)\n",
        encoding="utf-8",
    )

    result = scan_checkbox_tasks(wiki)

    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "TYPED_TASK_LINK_CARDINALITY",
        "SUPPORTING_LINK_MISSING",
    ]


def _client_for_inline_link_test(tmp_path: Path, wiki: Path) -> TestClient:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'projection.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": "brian", "password": "password"}).status_code == 204
    return client