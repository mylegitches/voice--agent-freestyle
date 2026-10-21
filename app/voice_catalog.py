from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Settings, get_settings
from .schemas import VoiceInfo


class VoiceCatalog:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._runtime_status: dict[str, tuple[str, str | None]] = {}

    @staticmethod
    def _read_metadata(config_path: Path) -> dict[str, Any]:
        with config_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def scan(self) -> list[VoiceInfo]:
        found: dict[Path, VoiceInfo] = {}
        for model_root in self.settings.model_roots:
            if not model_root.exists():
                continue
            for model_path in model_root.rglob("*.onnx"):
                model_path = model_path.resolve()
                if model_path in found:
                    continue
                config_path = Path(f"{model_path}.json")
                voice_id = model_path.stem
                if not config_path.exists():
                    found[model_path] = VoiceInfo(
                        id=voice_id,
                        name=voice_id,
                        model_path=self._display_path(model_path),
                        config_path=self._display_path(config_path),
                        sample_rate=None,
                        num_speakers=1,
                        language="unknown",
                        length_scale=1.0,
                        status="error",
                        error="Matching .onnx.json config is missing",
                    )
                    continue
                try:
                    metadata = self._read_metadata(config_path)
                    runtime_status, runtime_error = self._runtime_status.get(
                        str(model_path), ("untested", None)
                    )
                    found[model_path] = VoiceInfo(
                        id=voice_id,
                        name=voice_id.replace("_", " ").replace("-", " "),
                        model_path=self._display_path(model_path),
                        config_path=self._display_path(config_path),
                        sample_rate=metadata.get("audio", {}).get("sample_rate"),
                        num_speakers=max(1, int(metadata.get("num_speakers", 1) or 1)),
                        language=metadata.get("language", {}).get("code", "unknown"),
                        length_scale=float(metadata.get("inference", {}).get("length_scale", 1.0)),
                        status=runtime_status,
                        error=runtime_error,
                    )
                except Exception as exc:
                    found[model_path] = VoiceInfo(
                        id=voice_id,
                        name=voice_id,
                        model_path=self._display_path(model_path),
                        config_path=self._display_path(config_path),
                        sample_rate=None,
                        num_speakers=1,
                        language="unknown",
                        length_scale=1.0,
                        status="error",
                        error=f"Invalid voice config: {exc}",
                    )
        return sorted(found.values(), key=lambda voice: voice.name.casefold())

    def resolve_pair(self, model_path: str, config_path: str | None = None) -> tuple[Path, Path]:
        resolved_model = self._resolve_allowed(model_path)
        resolved_config = self._resolve_allowed(config_path or f"{model_path}.json")
        if resolved_model.suffix.lower() != ".onnx":
            raise ValueError("Voice model must be an .onnx file")
        if resolved_config.name != f"{resolved_model.name}.json":
            raise ValueError("Voice config must use the matching .onnx.json basename")
        if not resolved_model.is_file() or not resolved_config.is_file():
            raise ValueError("Voice model/config pair does not exist")
        return resolved_model, resolved_config

    def mark_runtime(self, model_path: Path, status: str, error: str | None = None) -> None:
        self._runtime_status[str(model_path.resolve())] = (status, error)

    def _resolve_allowed(self, value: str) -> Path:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = self.settings.root_dir / candidate
        candidate = candidate.resolve()
        allowed = [root.resolve() for root in self.settings.model_roots]
        if not any(candidate == root or root in candidate.parents for root in allowed):
            raise ValueError("Voice path must stay inside an allowed model directory")
        return candidate

    def _display_path(self, value: Path) -> str:
        try:
            return value.resolve().relative_to(self.settings.root_dir).as_posix()
        except ValueError:
            return str(value.resolve())


voice_catalog = VoiceCatalog()
