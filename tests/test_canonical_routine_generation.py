from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from lifeos.domain import Routine
from lifeos.main import create_app
from lifeos.scheduler import generate_due_once
from lifeos.wiki_store import WikiRepository


def test_scheduler_generation_writes_canonical_task_and_advances_routine(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Routines"}).json()
    routine = client.post(
        "/api/routines",
        json={
            "title": "Morning review",
            "cadence": "daily",
            "task_list_id": task_list["id"],
            "start_date": "2026-08-13",
        },
    ).json()

    assert generate_due_once(app, date(2026, 8, 13)) == 1

    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 1
    task = tasks[0]
    assert task["wiki_id"] == "tsk-rtn-morning-review-2026-08-13"
    task_record = WikiRepository(wiki).find_by_id(task["wiki_id"])
    assert task_record is not None
    assert task_record.fields["occurrence_key"] == "routine:rtn-morning-review:2026-08-13"
    assert task_record.fields["routine_wiki_id"] == routine["wiki_id"]
    routine_record = WikiRepository(wiki).find_by_id(routine["wiki_id"])
    assert routine_record is not None
    assert routine_record.fields["next_run_date"] == "2026-08-14"

    assert generate_due_once(app, date(2026, 8, 13)) == 0
    assert len(WikiRepository(wiki).list_records("task")) == 1
    assert len(client.get("/api/tasks").json()) == 1


def test_scheduler_writes_canonical_task_before_projection(tmp_path: Path, monkeypatch) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'source-first.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Routines"}).json()
    client.post(
        "/api/routines",
        json={
            "title": "Source-first generation",
            "cadence": "daily",
            "task_list_id": task_list["id"],
            "start_date": "2026-08-13",
        },
    )
    repository = app.state.wiki_repository
    original_write = repository.write
    events: list[str] = []

    def observed_write(*args, **kwargs):
        events.append(f"source:{args[0]}")
        return original_write(*args, **kwargs)

    def observed_flush(_session, _context):
        events.append("projection")

    monkeypatch.setattr(repository, "write", observed_write)
    event.listen(Session, "after_flush", observed_flush)
    try:
        assert generate_due_once(app, date(2026, 8, 13)) == 1
    finally:
        event.remove(Session, "after_flush", observed_flush)

    assert events[0] == "source:task"


def test_same_title_routines_generate_distinct_canonical_occurrences(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'same-title.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    first_list = client.post("/api/task-lists", json={"name": "First"}).json()
    second_list = client.post("/api/task-lists", json={"name": "Second"}).json()
    first = client.post(
        "/api/routines",
        json={"title": "Review", "cadence": "daily", "task_list_id": first_list["id"], "start_date": "2026-08-13"},
    ).json()
    second = client.post(
        "/api/routines",
        json={"title": "Review", "cadence": "daily", "task_list_id": second_list["id"], "start_date": "2026-08-13"},
    ).json()

    assert first["wiki_id"] != second["wiki_id"]
    assert generate_due_once(app, date(2026, 8, 13)) == 2

    tasks = client.get("/api/tasks").json()
    assert {task["wiki_id"] for task in tasks} == {
        f"tsk-{first['wiki_id']}-2026-08-13",
        f"tsk-{second['wiki_id']}-2026-08-13",
    }
    records = WikiRepository(wiki).list_records("task")
    assert len(records) == 2
    assert {record.fields["routine_wiki_id"] for record in records} == {first["wiki_id"], second["wiki_id"]}


def test_stale_routine_hash_does_not_create_occurrence_file(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'stale-routine.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Routines"}).json()
    routine = client.post(
        "/api/routines",
        json={"title": "Guard generation", "cadence": "daily", "task_list_id": task_list["id"], "start_date": "2026-08-13"},
    ).json()
    path = wiki / routine["wiki_path"]
    path.write_text(path.read_text(encoding="utf-8") + "\nExternal edit.\n", encoding="utf-8")

    response = client.post(f"/api/routines/{routine['id']}/generate", params={"on": "2026-08-13"})

    assert response.status_code == 409
    assert app.state.wiki_repository.list_records("task") == []
    assert client.get("/api/tasks").json() == []


def test_scheduler_rejects_routine_identity_path_disagreement_before_writes(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'routine-identity-path.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Routines"}).json()
    first = client.post(
        "/api/routines",
        json={"title": "First routine", "cadence": "daily", "task_list_id": task_list["id"], "start_date": "2026-08-13"},
    ).json()
    second = client.post(
        "/api/routines",
        json={"title": "Second routine", "cadence": "daily", "task_list_id": task_list["id"], "start_date": "2026-08-13"},
    ).json()
    with app.state.session_factory() as session:
        projected = session.get(Routine, first["id"])
        projected.wiki_path = second["wiki_path"]
        projected.wiki_hash = second["wiki_hash"]
        session.commit()
    before = {item["wiki_path"]: (wiki / item["wiki_path"]).read_bytes() for item in (first, second)}

    response = client.post(f"/api/routines/{first['id']}/generate", params={"on": "2026-08-13"})

    assert response.status_code == 409
    assert "identity and path disagree" in response.text
    assert {path: (wiki / path).read_bytes() for path in before} == before
    assert app.state.wiki_repository.list_records("task") == []
    assert client.get("/api/tasks").json() == []


def test_scheduler_rejects_non_routine_id_without_path_before_writes(tmp_path: Path) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'routine-wrong-type.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Routines"}).json()
    routine = client.post(
        "/api/routines",
        json={"title": "Wrong type guard", "cadence": "daily", "task_list_id": task_list["id"], "start_date": "2026-08-13"},
    ).json()
    canonical_task = app.state.wiki_repository.write(
        "task",
        "Canonical task owner",
        {"id": "tsk-not-a-routine", "status": "open", "task_list": "Routines"},
    )
    routine_path = wiki / routine["wiki_path"]
    task_path = wiki / canonical_task.path
    before = {routine["wiki_path"]: routine_path.read_bytes(), canonical_task.path: task_path.read_bytes()}
    with app.state.session_factory() as session:
        projected = session.get(Routine, routine["id"])
        projected.wiki_id = canonical_task.record_id
        projected.wiki_path = None
        projected.wiki_hash = canonical_task.content_hash
        session.commit()

    response = client.post(f"/api/routines/{routine['id']}/generate", params={"on": "2026-08-13"})

    assert response.status_code == 409
    assert "not a routine" in response.text
    assert {path: (wiki / path).read_bytes() for path in before} == before
    remaining_tasks = app.state.wiki_repository.list_records("task")
    assert len(remaining_tasks) == 1
    assert (remaining_tasks[0].record_id, remaining_tasks[0].path, remaining_tasks[0].content_hash) == (
        canonical_task.record_id,
        canonical_task.path,
        canonical_task.content_hash,
    )
    assert client.get("/api/tasks").json() == []


def test_post_occurrence_failure_reports_reconciliation_required(tmp_path: Path, monkeypatch) -> None:
    wiki = tmp_path / "wiki"
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'partial-routine.db'}",
        auth_username="brian",
        auth_password="password",
        scheduler_enabled=False,
        wiki_root=str(wiki),
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Routines"}).json()
    routine = client.post(
        "/api/routines",
        json={"title": "Partial generation", "cadence": "daily", "task_list_id": task_list["id"], "start_date": "2026-08-13"},
    ).json()
    repository = app.state.wiki_repository
    original_write = repository.write

    def fail_routine_advance(record_type, *args, **kwargs):
        if record_type == "routine" and kwargs.get("expected_hash"):
            raise OSError("simulated routine write failure")
        return original_write(record_type, *args, **kwargs)

    monkeypatch.setattr(repository, "write", fail_routine_advance)
    response = client.post(f"/api/routines/{routine['id']}/generate", params={"on": "2026-08-13"})

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "canonical_source_written_projection_failed"
    assert detail["wiki_id"] == f"tsk-{routine['wiki_id']}-2026-08-13"
    assert (wiki / detail["wiki_path"]).is_file()
    assert client.get("/api/tasks").json() == []
