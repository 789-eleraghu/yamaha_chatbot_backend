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
    assert data["database_type"] in ("sqlite", "clickhouse")

def test_out_of_domain_query_skips_tools_and_fallbacks():
    response = client.post("/api/chat", json={"message": "who won the cricket match today?"})
    assert response.status_code == 200
    text = response.text
    # Should NOT trigger tool-input-available for energy tools
    assert "get_energy_consumption" not in text
    assert "tool-input-available" not in text
    # Should explain domain boundary or confidentiality
    assert "Yamaha" in text or "confidential" in text

def test_ambiguous_query_requests_clarification():
    response = client.post("/api/chat", json={"message": "show me consumption"})
    assert response.status_code == 200
    text = response.text
    # Should request clarification and NOT dump dummy incomer load profile
    assert any(term in text.lower() for term in ("clarif", "breakdown", "which date", "more context", "specify", "scope"))
