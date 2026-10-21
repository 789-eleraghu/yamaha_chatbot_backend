"""
Unit & Integration Tests for Chat History & Real-Time Functionality
Tests:
- chats table CRUD
- chat_history table message tracking
- realtime_chat_events table
- realtime_device_telemetry table
- Title generation
- API endpoints: /api/chats, /api/chats/{id}, /api/chats/{id}/messages, /api/chat, /api/telemetry/live
"""

import json
from fastapi.testclient import TestClient
from src.api.main import app
from src.db.chat_history import chat_repo, generate_chat_title

client = TestClient(app)

def test_chat_repo_crud():
    # 1. Create chat
    chat = chat_repo.create_chat(user_id="unit_test_user", name="Test Title")
    chat_id = chat["chat_id"]
    assert chat_id is not None
    assert chat["name"] == "Test Title"
    assert chat["is_archived"] == 0

    # 2. Save user message
    u_msg_id = chat_repo.save_message(chat_id, "user", "What is shift consumption on 2026-03-01?")
    assert u_msg_id > 0

    # 3. Record real-time event
    ev_id = chat_repo.record_realtime_event(chat_id, "tool_start", {"tool": "get_shift_wise_consumption"}, u_msg_id)
    assert ev_id is not None

    # 4. Save tool message
    t_msg_id = chat_repo.save_message(chat_id, "tool", json.dumps({"shift_a": 1200}), metadata={"tool_name": "get_shift_wise_consumption"})
    assert t_msg_id > u_msg_id

    # 5. Save assistant message
    a_msg_id = chat_repo.save_message(chat_id, "assistant", "Here is your shift breakdown.", metadata={"key_metrics": {"total_kwh": 3500}})
    assert a_msg_id > t_msg_id

    # 6. Read messages
    messages = chat_repo.get_chat_messages(chat_id)
    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "tool"
    assert messages[2]["role"] == "assistant"
    assert messages[2]["metadata"]["key_metrics"]["total_kwh"] == 3500

    # 7. Update title
    success = chat_repo.set_chat_title(chat_id, "Renamed Title")
    assert success is True
    updated = chat_repo.get_chat(chat_id)
    assert updated["name"] == "Renamed Title"

    # 8. Archive chat
    assert chat_repo.archive_chat(chat_id, True) is True
    archived = chat_repo.get_chat(chat_id)
    assert archived["is_archived"] == 1

    # Active chats should exclude it
    active_chats = chat_repo.list_chats(user_id="unit_test_user", include_archived=False)
    assert not any(c["chat_id"] == chat_id for c in active_chats)

    # 9. Clean up
    assert chat_repo.delete_chat(chat_id) is True
    assert chat_repo.get_chat(chat_id) is None
    # Cascaded messages should also be gone
    assert len(chat_repo.get_chat_messages(chat_id)) == 0

def test_title_generation():
    assert "Shift" in generate_chat_title("What was the shift consumption yesterday?")
    assert "Peak" in generate_chat_title("Check peak kVA on south utilities transformer")
    assert "Tariff" in generate_chat_title("Calculate cost under tariff HT_1")
    title_dg = generate_chat_title("How many runs did the diesel generator do?")
    assert any(term in title_dg for term in ("DG", "Diesel", "Generator"))

def test_api_chat_management():
    # POST /api/chats
    res = client.post("/api/chats", json={"user_id": "api_user", "name": "API Test Chat"})
    assert res.status_code == 200
    data = res.json()
    chat_id = data["chat_id"]
    assert data["name"] == "API Test Chat"

    # GET /api/chats
    list_res = client.get("/api/chats?user_id=api_user")
    assert list_res.status_code == 200
    chats = list_res.json()
    assert any(c["chat_id"] == chat_id for c in chats)

    # PATCH /api/chats/{chat_id}
    patch_res = client.patch(f"/api/chats/{chat_id}", json={"name": "Updated API Title"})
    assert patch_res.status_code == 200
    assert patch_res.json()["name"] == "Updated API Title"

    # POST /api/chats/{chat_id}/archive
    arch_res = client.post(f"/api/chats/{chat_id}/archive")
    assert arch_res.status_code == 200
    assert arch_res.json()["status"] == "archived"

    # DELETE /api/chats/{chat_id}
    del_res = client.delete(f"/api/chats/{chat_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

def test_live_telemetry_endpoint():
    res = client.get("/api/telemetry/live")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["count"] > 0
    assert any(item["device_id"] == "HT_Room" for item in data["telemetry"])

def test_streaming_chat_endpoint():
    # Test POST /api/chat with streaming response
    payload = {
        "message": "What is the shift-wise consumption for 2026-10-20?",
        "user_id": "stream_user"
    }
    res = client.post("/api/chat", json=payload)
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    assert res.headers.get("x-vercel-ai-ui-message-stream") == "v1"

    body_text = res.text
    assert "tool-input-available" in body_text
    assert "tool-output-available" in body_text
    assert "text-delta" in body_text
    assert "[DONE]" in body_text

def test_load_langchain_history_filters_orphan_tools():
    from src.services.chat_service import chat_service
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

    chat = chat_repo.create_chat(user_id="test_filter_user", name="Filter Test")
    cid = chat["chat_id"]
    try:
        u_id = chat_repo.save_message(cid, "user", "What was the breakdown today?")
        t_id = chat_repo.save_message(cid, "tool", '{"result": 123}', metadata={"tool_name": "calc", "tool_call_id": "call_123"})
        a_id = chat_repo.save_message(cid, "assistant", "Here is the breakdown summary.")
        u2_id = chat_repo.save_message(cid, "user", "Can you make it a pie chart?")

        # When loading history for u2_id turn:
        history = chat_service.load_langchain_history(chat_id=cid, current_user_msg_id=u2_id)
        
        # Verify orphan tool messages are excluded to preserve Bedrock API schema invariants
        assert len(history) == 2
        assert isinstance(history[0], HumanMessage)
        assert history[0].content == "What was the breakdown today?"
        assert isinstance(history[1], AIMessage)
        assert history[1].content == "Here is the breakdown summary."
        assert not any(isinstance(m, ToolMessage) for m in history)
    finally:
        chat_repo.delete_chat(cid)
