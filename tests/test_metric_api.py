from fastapi.testclient import TestClient

from lifeos.domain import AuditRecord
from lifeos.main import create_app


def _client(tmp_path) -> tuple[TestClient, object]:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
    )
    client = TestClient(app)
    client.post("/auth/login", json={"username": "brian", "password": "password"})
    return client, app


def test_metric_definition_and_typed_entry_round_trip(tmp_path) -> None:
    client, app = _client(tmp_path)
    metric = client.post(
        "/api/metrics",
        json={"slug": "energy", "label": "Energy", "data_type": "rating", "unit": "0-10"},
    )
    assert metric.status_code == 201
    metric_id = metric.json()["id"]
    entry = client.post(
        f"/api/metrics/{metric_id}/entries",
        json={"recorded_on": "2026-08-12", "value": 7, "estimated": True, "source": "user"},
    )
    assert entry.status_code == 201
    assert entry.json()["value"] == 7
    assert entry.json()["estimated"] is True
    assert client.get(f"/api/metrics/{metric_id}/entries").json()[0]["slug"] == "energy"
    with app.state.session_factory() as session:
        assert session.query(AuditRecord).filter_by(entity_type="metric_entry", action="created").count() == 1


def test_metric_rejects_wrong_type_and_archived_writes(tmp_path) -> None:
    client, _app = _client(tmp_path)
    metric_id = client.post(
        "/api/metrics",
        json={"slug": "steps", "label": "Steps", "data_type": "count"},
    ).json()["id"]
    assert (
        client.post(f"/api/metrics/{metric_id}/entries", json={"recorded_on": "2026-08-12", "value": -1}).status_code
        == 422
    )
    assert client.patch(f"/api/metrics/{metric_id}", json={"status": "archived"}).status_code == 200
    assert (
        client.post(f"/api/metrics/{metric_id}/entries", json={"recorded_on": "2026-08-12", "value": 3}).status_code
        == 409
    )
