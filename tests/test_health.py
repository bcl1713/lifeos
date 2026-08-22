from fastapi.testclient import TestClient

from lifeos import __version__
from lifeos.main import app

client = TestClient(app)


def test_health_endpoint_reports_service_status() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "lifeos",
        "package_version": __version__,
        "build_version": "local-dev",
        "build_revision": "unknown",
    }


def test_health_endpoint_distinguishes_injected_build_metadata() -> None:
    from lifeos.main import create_app

    app = create_app(
        database_url="sqlite://",
        build_version="v0.6.3-dev.30",
        build_revision="5e14d46fad12a73e00b5d7f629f9c85141ea80e9",
        scheduler_enabled=False,
    )

    response = TestClient(app).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "lifeos",
        "package_version": __version__,
        "build_version": "v0.6.3-dev.30",
        "build_revision": "5e14d46fad12a73e00b5d7f629f9c85141ea80e9",
    }
