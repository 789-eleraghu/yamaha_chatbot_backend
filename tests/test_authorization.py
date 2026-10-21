"""
Unit & Integration Tests for Authorization & Access Control
"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from src.api.main import app
from src.services.authorization import auth_service
from src.services.chat_service import chat_service

client = TestClient(app)

def test_identifier_sanitization():
    # Valid
    assert auth_service.sanitize_identifier("user_123") == "user_123"
    assert auth_service.sanitize_identifier("uuid-1234-abcd") == "uuid-1234-abcd"

    # Invalid / Injection
    with pytest.raises(HTTPException):
        auth_service.sanitize_identifier("user; DROP TABLE chats;--")

    with pytest.raises(HTTPException):
        auth_service.sanitize_identifier("../../../etc/passwd")

def test_cross_user_access_rejection():
    # Create chat for alice
    chat_alice = chat_service.create_chat(user_id="alice", name="Alice Private Chat")
    alice_cid = chat_alice["chat_id"]

    # Bob attempts to view Alice's chat
    with pytest.raises(HTTPException) as exc_info:
        chat_service.get_chat(chat_id=alice_cid, user_id="bob")
    assert exc_info.value.status_code == 403

    # Bob attempts to modify Alice's chat
    with pytest.raises(HTTPException) as exc_info:
        chat_service.update_chat(chat_id=alice_cid, user_id="bob", name="Hacked Name")
    assert exc_info.value.status_code == 403

    # Bob attempts to delete Alice's chat
    with pytest.raises(HTTPException) as exc_info:
        chat_service.delete_chat(chat_id=alice_cid, user_id="bob")
    assert exc_info.value.status_code == 403

    # Alice can access her own chat
    owned = chat_service.get_chat(chat_id=alice_cid, user_id="alice")
    assert owned["chat_id"] == alice_cid

    # Cleanup
    chat_service.delete_chat(chat_id=alice_cid, user_id="alice")

def test_api_cross_user_endpoints():
    # Create chat owned by tenant_a
    res = client.post("/api/chats", json={"user_id": "tenant_a", "name": "Tenant A Chat"})
    assert res.status_code == 200
    cid = res.json()["chat_id"]

    # Tenant B tries to delete Tenant A's chat
    del_res = client.delete(f"/api/chats/{cid}", headers={"X-User-Id": "tenant_b"})
    assert del_res.status_code == 403

    # Tenant B tries to get Tenant A's chat
    get_res = client.get(f"/api/chats/{cid}", headers={"X-User-Id": "tenant_b"})
    assert get_res.status_code == 403

    # Tenant A deletes their own chat
    del_res_a = client.delete(f"/api/chats/{cid}", headers={"X-User-Id": "tenant_a"})
    assert del_res_a.status_code == 200
