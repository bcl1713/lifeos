from fastapi.testclient import TestClient

from lifeos.main import app

client = TestClient(app)


def test_health_endpoint_reports_service_status() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "lifeos"
