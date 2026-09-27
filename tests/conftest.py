import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from scripts.seed_demo import seed


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        _env_file=None, readyline_db=str(tmp_path / "test.sqlite3"), nvidia_api_key="test-credential-not-real"
    )
    app = create_app(settings, start_worker=False)
    with TestClient(app, headers={"X-ReadyLine": "1"}) as client:
        credentials = {"username": "operator", "password": "test-password-12345"}
        assert client.post("/api/auth/setup", json=credentials).status_code == 201
        assert client.post("/api/auth/login", json=credentials).status_code == 200
        yield client


@pytest.fixture
def seeded(client):
    seed(client.app.state.db)
    return client
