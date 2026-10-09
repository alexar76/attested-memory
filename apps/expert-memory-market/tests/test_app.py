from fastapi.testclient import TestClient

from expert_market.app import app


def test_health():
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json()["product"] == "expert-memory-market"


def test_listings_require_saas_key():
    response = TestClient(app).get("/api/listings")
    assert response.status_code == 401
