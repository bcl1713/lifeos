
from fastapi.testclient import TestClient

from lifeos.main import create_app


def test_browser_login_protects_user_route_and_logout_revokes_session(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="correct horse battery staple",
    )
    client = TestClient(app)

    assert client.get("/auth/me").status_code == 401

    login = client.post(
        "/auth/login",
        json={"username": "brian", "password": "correct horse battery staple"},
    )
    assert login.status_code == 204
    assert "lifeos_session" in login.cookies
    assert client.get("/auth/me").json() == {"username": "brian"}

    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_agent_token_is_bearer_authenticated_and_can_be_revoked(tmp_path) -> None:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'lifeos.db'}",
        auth_username="brian",
        auth_password="password",
        agent_token="agent-secret",
    )
    client = TestClient(app)

    assert client.get("/auth/agent", headers={"Authorization": "Bearer agent-secret"}).json() == {
        "actor": "agent"
    }
    assert client.get("/auth/agent").status_code == 401
    assert client.get("/auth/agent", headers={"Authorization": "Bearer wrong"}).status_code == 401
