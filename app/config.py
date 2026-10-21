from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]


@dataclass(slots=True)
class Settings:
    root_dir: Path = ROOT_DIR
    host: str = "127.0.0.1"
    port: int = 8000
    database_url: str = ""
    llm_base_url: str = "https://ollama.com/v1"
    llm_model: str = "minimax-m3"
    llm_timeout_seconds: float = 45.0
    llm_reasoning_effort: str | None = "none"
    ollama_api_key: str | None = None
    model_roots: list[Path] = field(default_factory=list)
    piper_host: str = ""
    piper_port: int = 10200
    piper_languages: list[str] = field(default_factory=list)
    save_session_audio: bool = False
    whisper_model: str = "small.en"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    room_defaults: dict[str, Any] = field(default_factory=dict)

    @property
    def data_dir(self) -> Path:
        return self.root_dir / "data"

    @property
    def web_dist(self) -> Path:
        return self.root_dir / "web" / "dist"


def _nested(data: dict[str, Any], section: str, key: str, default: Any) -> Any:
    return data.get(section, {}).get(key, default)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(ROOT_DIR / ".env")
    config_path = ROOT_DIR / "config.yaml"
    raw: dict[str, Any] = {}
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    roots = [ROOT_DIR / item for item in _nested(raw, "audio", "model_roots", ["models"])]
    database_url = os.getenv(
        "VOICE_ROOM_DATABASE_URL",
        f"sqlite+aiosqlite:///{(ROOT_DIR / 'data' / 'voice-room.sqlite3').as_posix()}",
    )
    return Settings(
        host=str(_nested(raw, "server", "host", "127.0.0.1")),
        port=int(_nested(raw, "server", "port", 8000)),
        database_url=database_url,
        llm_base_url=str(_nested(raw, "llm", "base_url", "https://ollama.com/v1")),
        llm_model=os.getenv(
            "VOICE_ROOM_LLM_MODEL",
            str(_nested(raw, "llm", "model", "minimax-m3")),
        ),
        llm_timeout_seconds=float(_nested(raw, "llm", "timeout_seconds", 45)),
        llm_reasoning_effort=_nested(raw, "llm", "reasoning_effort", "none") or None,
        ollama_api_key=os.getenv("OLLAMA_API_KEY") or None,
        model_roots=roots,
        piper_host=os.getenv("VOICE_ROOM_PIPER_HOST", str(_nested(raw, "tts", "wyoming_host", "") or "")),
        piper_port=int(os.getenv("VOICE_ROOM_PIPER_PORT", _nested(raw, "tts", "wyoming_port", 10200))),
        piper_languages=list(_nested(raw, "tts", "languages", []) or []),
        save_session_audio=bool(_nested(raw, "audio", "save_session_audio", False)),
        whisper_model=os.getenv(
            "VOICE_ROOM_WHISPER_MODEL", str(_nested(raw, "stt", "model", "small.en"))
        ),
        whisper_device=str(_nested(raw, "stt", "device", "cpu")),
        whisper_compute_type=str(_nested(raw, "stt", "compute_type", "int8")),
        room_defaults=dict(raw.get("room_defaults", {})),
    )
