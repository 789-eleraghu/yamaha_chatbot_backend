"""
API Endpoint Tests
"""

from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()

def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database_status"] == "healthy"
    assert data["database_type"] == "sqlite"
