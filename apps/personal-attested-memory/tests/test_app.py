from fastapi.testclient import TestClient

from personal_memory.app import app


def test_health():
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json()["product"] == "personal-attested-memory"


def test_memory_requires_actor_and_saas_proof():
    response = TestClient(app).post("/api/memories", json={"title": "x", "content": "y"})
    assert response.status_code == 401
