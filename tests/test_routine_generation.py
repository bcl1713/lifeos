from fastapi.testclient import TestClient

from lifeos.main import create_app
from lifeos.routine_service import advance_occurrence


def test_advanced_routine_cadences() -> None:
    from datetime import date

    assert advance_occurrence(date(2026, 8, 14), "weekdays:0,2,4") == date(2026, 8, 17)
    assert advance_occurrence(date(2026, 8, 12), "weekdays:0,2,4") == date(2026, 8, 14)
    assert advance_occurrence(date(2026, 8, 12), "interval:3") == date(2026, 8, 15)
    try:
        advance_occurrence(date(2026, 8, 12), "interval:0")
    except ValueError as exc:
        assert "at least one day" in str(exc)
    else:
        raise AssertionError("invalid interval was accepted")


def test_minimum_frequency_compliance_reporting(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Compliance"}).json()
    routine = client.post(
        "/api/routines",
        json={
            "title": "Read",
            "cadence": "daily",
            "start_date": "2026-08-10",
            "task_list_id": task_list["id"],
            "minimum_occurrences": 3,
            "frequency_window_days": 7,
        },
    ).json()
    rid = routine["id"]
    assert client.get(f"/api/routines/{rid}/frequency", params={"on": "2026-08-16"}).json()["compliance"] == "missed"
    assert client.post(f"/api/routines/{rid}/generate", params={"on": "2026-08-12"}).json()["generated"] == 3
    tasks = client.get("/api/tasks", params={"limit": 10}).json()
    client.post(f"/api/tasks/{tasks[0]['id']}/complete")
    recovering = client.get(f"/api/routines/{rid}/frequency", params={"on": "2026-08-16"}).json()
    assert recovering["compliance"] == "recovering"
    client.post(f"/api/tasks/{tasks[1]['id']}/complete")
    client.post(f"/api/tasks/{tasks[2]['id']}/complete")
    on_target = client.get(f"/api/routines/{rid}/frequency", params={"on": "2026-08-16"}).json()
    assert on_target["compliance"] == "on_target"
    ordinary = client.post(
        "/api/routines",
        json={"title": "No target", "cadence": "daily", "start_date": "2026-08-10", "task_list_id": task_list["id"]},
    ).json()
    assert client.get(f"/api/routines/{ordinary['id']}/frequency").status_code == 409


def test_minimum_frequency_routine_configuration(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Habits"}).json()
    routine = client.post(
        "/api/routines",
        json={
            "title": "Exercise",
            "cadence": "daily",
            "start_date": "2026-08-12",
            "task_list_id": task_list["id"],
            "minimum_occurrences": 3,
            "frequency_window_days": 7,
        },
    )
    assert routine.status_code == 201
    assert routine.json()["minimum_occurrences"] == 3
    assert routine.json()["frequency_window_days"] == 7
    assert (
        client.post(
            "/api/routines",
            json={
                "title": "Incomplete frequency",
                "cadence": "daily",
                "start_date": "2026-08-12",
                "task_list_id": task_list["id"],
                "minimum_occurrences": 3,
            },
        ).status_code
        == 422
    )
    assert client.patch(f"/api/routines/{routine.json()['id']}", json={"frequency_window_days": 2}).status_code == 422


def test_routine_generation_catches_up_and_is_idempotent(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Routines"}).json()
    routine = client.post(
        "/api/routines",
        json={
            "title": "Take bins out",
            "cadence": "daily",
            "task_list_id": task_list["id"],
            "start_date": "2026-08-11",
        },
    )
    assert routine.status_code == 201
    routine_id = routine.json()["id"]

    first = client.post(f"/api/routines/{routine_id}/generate", params={"on": "2026-08-13"})
    assert first.status_code == 200
    assert first.json()["generated"] == 3

    second = client.post(f"/api/routines/{routine_id}/generate", params={"on": "2026-08-13"})
    assert second.status_code == 200
    assert second.json()["generated"] == 0

    tasks = client.get("/api/tasks", params={"limit": 10}).json()
    assert [task["due_date"] for task in tasks] == ["2026-08-11", "2026-08-12", "2026-08-13"]
    assert all(task["routine_id"] == routine_id for task in tasks)
    assert client.get("/api/routines").json()[0]["next_run_date"] == "2026-08-14"


def test_generate_all_routines_processes_active_routines_once(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Routines"}).json()
    for title in ("Feed pets", "Review calendar"):
        response = client.post(
            "/api/routines",
            json={
                "title": title,
                "cadence": "daily",
                "task_list_id": task_list["id"],
                "start_date": "2026-08-13",
            },
        )
        assert response.status_code == 201

    generated = client.post("/api/routines/generate", params={"on": "2026-08-13"})
    assert generated.status_code == 200
    assert generated.json()["generated"] == 2
    assert client.post("/api/routines/generate", params={"on": "2026-08-13"}).json()["generated"] == 0


def test_routine_skip_advances_without_creating_an_occurrence(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    task_list = client.post("/api/task-lists", json={"name": "Routines"}).json()
    routine = client.post(
        "/api/routines",
        json={"title": "Stretch", "cadence": "daily", "task_list_id": task_list["id"], "start_date": "2026-08-11"},
    ).json()
    routine_id = routine["id"]
    skip = client.post(
        f"/api/routines/{routine_id}/skip",
        json={"scheduled_date": "2026-08-11", "reason": "Travel"},
    )
    assert skip.status_code == 201
    duplicate = client.post(
        f"/api/routines/{routine_id}/skip",
        json={"scheduled_date": "2026-08-11", "reason": "Different wording"},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == skip.json()["id"]
    generated = client.post(f"/api/routines/{routine_id}/generate", params={"on": "2026-08-12"})
    assert generated.json()["generated"] == 1
    tasks = client.get("/api/tasks", params={"limit": 10}).json()
    assert [task["due_date"] for task in tasks] == ["2026-08-12"]
