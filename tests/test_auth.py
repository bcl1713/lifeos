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

    assert client.get("/auth/agent", headers={"Authorization": "Bearer agent-secret"}).json() == {"actor": "agent"}
    assert client.get("/auth/agent").status_code == 401
    assert client.get("/auth/agent", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_configured_credentials_rotate_existing_records(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'lifeos.db'}"
    first = create_app(database_url=database_url, auth_username="brian", auth_password="old", agent_token="old-agent")
    first_client = TestClient(first)
    assert first_client.post("/auth/login", json={"username": "brian", "password": "old"}).status_code == 204

    second = create_app(database_url=database_url, auth_username="brian", auth_password="new", agent_token="new-agent")
    second_client = TestClient(second)
    assert second_client.post("/auth/login", json={"username": "brian", "password": "old"}).status_code == 401
    assert second_client.post("/auth/login", json={"username": "brian", "password": "new"}).status_code == 204
    assert second_client.get("/auth/agent", headers={"Authorization": "Bearer old-agent"}).status_code == 401
    assert second_client.get("/auth/agent", headers={"Authorization": "Bearer new-agent"}).status_code == 200
