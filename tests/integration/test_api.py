from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def character_payload(name: str) -> dict:
    return {
        "name": name,
        "voice_path": "models/en_US-alfv1-medium.onnx",
        "voice_config_path": "models/en_US-alfv1-medium.onnx.json",
        "speaker_id": 0,
        "length_scale": 1,
        "system_prompt": f"You are {name}. Be concise and curious.",
        "eagerness": 0.5,
        "max_words": 50,
        "color": "#7c5cff",
        "avatar": None,
    }


def test_health_and_crud_flow() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["voices"]["count"] == 11

        first = client.post("/api/characters", json=character_payload("Ada"))
        second = client.post("/api/characters", json=character_payload("Grace"))
        assert first.status_code == 201
        assert second.status_code == 201

        room = client.post(
            "/api/rooms",
            json={
                "name": "Test Room",
                "safe_word": "end test",
                "settings": {"max_context_lines": 12},
                "character_ids": [first.json()["id"], second.json()["id"]],
            },
        )
        assert room.status_code == 201
        assert [row["name"] for row in room.json()["characters"]] == ["Ada", "Grace"]

        session = client.post(f"/api/rooms/{room.json()['id']}/session", json={})
        assert session.status_code == 200
        transcript = client.get(f"/api/sessions/{session.json()['id']}/transcript")
        assert transcript.status_code == 200
        assert transcript.json() == []


def test_websocket_reports_missing_llm_key_without_losing_kickoff() -> None:
    with TestClient(app) as client:
        one = client.post("/api/characters", json=character_payload("One")).json()
        two = client.post("/api/characters", json=character_payload("Two")).json()
        room = client.post(
            "/api/rooms",
            json={"name": "Socket", "safe_word": None, "settings": {}, "character_ids": [one["id"], two["id"]]},
        ).json()
        session = client.post(f"/api/rooms/{room['id']}/session", json={}).json()
        with client.websocket_connect(f"/ws/rooms/{room['id']}?session_id={session['id']}") as socket:
            assert socket.receive_json()["type"] == "snapshot"
            socket.send_json({"type": "start", "command_id": "1", "topic": "Talk about testing"})
            messages = [socket.receive_json() for _ in range(4)]
            assert any(message["type"] == "line_final" for message in messages)
            assert any(message.get("code") == "llm_not_configured" for message in messages)
            assert messages[-1]["type"] == "state"
            assert messages[-1]["state"] == "paused"
