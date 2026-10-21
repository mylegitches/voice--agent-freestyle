from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tts import tts_service
from app.voice_catalog import voice_catalog


async def main() -> int:
    failures = 0
    for voice in voice_catalog.scan():
        try:
            audio = await tts_service.synthesize(
                "Voice check complete.",
                voice.model_path,
                voice.config_path,
                speaker_id=0,
                length_scale=voice.length_scale,
            )
            valid = audio[:4] == b"RIFF" and len(audio) > 44
            print(f"{'PASS' if valid else 'FAIL'} {voice.id}: {len(audio)} bytes")
            failures += 0 if valid else 1
        except Exception as exc:
            failures += 1
            print(f"FAIL {voice.id}: {exc}")
    return failures


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
