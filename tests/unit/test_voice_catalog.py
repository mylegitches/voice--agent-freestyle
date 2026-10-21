from __future__ import annotations

from app.voice_catalog import voice_catalog


def test_supplied_voice_catalog_is_discoverable() -> None:
    voices = voice_catalog.scan()
    assert len(voices) == 11
    assert all(voice.sample_rate == 22050 for voice in voices)
    glados = next(voice for voice in voices if "glados" in voice.id)
    assert glados.num_speakers == 1
    assert glados.language == "unknown"


def test_catalog_rejects_path_escape() -> None:
    try:
        voice_catalog.resolve_pair("../outside.onnx")
    except ValueError as exc:
        assert "allowed model directory" in str(exc)
    else:
        raise AssertionError("Path escape was accepted")
