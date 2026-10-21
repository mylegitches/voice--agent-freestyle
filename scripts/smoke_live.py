from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SMOKE_DB = ROOT / "data" / "live-smoke.sqlite3"
SMOKE_DB.unlink(missing_ok=True)
os.environ["VOICE_ROOM_DATABASE_URL"] = f"sqlite+aiosqlite:///{SMOKE_DB.as_posix()}"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def character(name: str, color: str) -> dict:
    return {
        "name": name,
        "voice_path": "models/en_US-alfv1-medium.onnx",
        "voice_config_path": "models/en_US-alfv1-medium.onnx.json",
        "speaker_id": 0,
        "length_scale": 1,
        "system_prompt": f"You are {name}. Be warm, concrete, and very concise.",
        "eagerness": 0.5,
        "max_words": 24,
        "color": color,
        "avatar": None,
    }


def main() -> int:
    try:
        with TestClient(app) as client:
            health = client.get("/api/health?verify_llm=true").json()
            if not health["llm"]["verified"]:
                raise RuntimeError(health["llm"]["message"])
            one = client.post("/api/characters", json=character("Ada", "#ff774d")).json()
            two = client.post("/api/characters", json=character("Grace", "#7c5cff")).json()
            room = client.post(
                "/api/rooms",
                json={
                    "name": "Live Smoke",
                    "safe_word": "end smoke",
                    "settings": {"max_context_lines": 12},
                    "character_ids": [one["id"], two["id"]],
                },
            ).json()
            session = client.post(f"/api/rooms/{room['id']}/session", json={}).json()
            events: set[str] = set()
            audio_bytes = 0
            generated = ""
            with client.websocket_connect(
                f"/ws/rooms/{room['id']}?session_id={session['id']}"
            ) as socket:
                events.add(socket.receive_json()["type"])
                socket.send_json(
                    {
                        "type": "start",
                        "command_id": "smoke-start",
                        "topic": "In one sentence, say why testing matters.",
                    }
                )
                while not ({"bid", "line_final", "audio_start"} <= events and audio_bytes):
                    message = socket.receive()
                    if message.get("bytes") is not None:
                        audio_bytes += len(message["bytes"])
                        continue
                    if message.get("text") is None:
                        continue
                    payload = json.loads(message["text"])
                    events.add(payload["type"])
                    if payload["type"] == "line_final" and payload["line"]["character_id"]:
                        generated = payload["line"]["text"]
                socket.send_json({"type": "stop", "command_id": "smoke-stop"})
                while True:
                    payload = socket.receive_json()
                    if payload.get("type") == "state" and payload.get("state") == "stopped":
                        break
            assert generated
            assert audio_bytes > 44
            print(f"PASS live loop: {generated!r} ({audio_bytes} audio bytes)")
        return 0
    finally:
        SMOKE_DB.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
