from __future__ import annotations

import os
from pathlib import Path


TEST_DB = Path(__file__).resolve().parents[1] / "data" / "test-voice-room.sqlite3"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
TEST_DB.unlink(missing_ok=True)
os.environ["VOICE_ROOM_DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB.as_posix()}"
os.environ.pop("OLLAMA_API_KEY", None)


def pytest_sessionfinish() -> None:
    TEST_DB.unlink(missing_ok=True)
