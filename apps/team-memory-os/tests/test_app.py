from fastapi.testclient import TestClient

from team_memory.app import app


def test_health():
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json()["product"] == "team-memory-os"


def test_team_creation_requires_saas_key_and_actor():
    response = TestClient(app).post("/api/teams", json={"name": "Example"})
    assert response.status_code == 401
