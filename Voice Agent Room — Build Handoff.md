# Voice Agent Room — Build Handoff

Local FastAPI web app: build voice personas (Piper ONNX voice + personality), group them into rooms, kick a room off by mic (faster-whisper) or a typed topic, and let the personas converse through Ollama Cloud until you pause or stop. One shared LLM; personality is per-character system prompt. Audio is output-only TTS plus one mic input for you — agents exchange **text**, never listen to each other, so no agent-to-agent STT, no talking over each other.

## Stack

- **Backend**: Python 3.11+, FastAPI + Uvicorn. One WebSocket per live room carries transcript lines, audio, and control events.
- **Frontend**: SPA with three views — Characters, Rooms, Live room. Plain JS + htmx/Alpine is enough; React if you prefer. Browser handles mic capture and audio playback.
- **LLM**: Ollama Cloud, OpenAI-compatible. One model (`minimax-m3:cloud`) for every persona; the only per-speaker differences are the system prompt and the shared transcript.
- **TTS**: Piper (ONNX via onnxruntime). One voice model per character, loaded once and kept warm.
- **STT**: faster-whisper (CTranslate2) + silero-vad (ONNX) for your mic only.
- **Store**: SQLite for characters, rooms, sessions, transcript. Voice files on disk under `models/voices/`.

## LLM — Ollama Cloud

OpenAI-compatible endpoint, so use the `openai` SDK and only change the base URL and key. Base URL `https://ollama.com/v1`, auth `Authorization: Bearer $OLLAMA_API_KEY` ([Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)). Keep the key in `.env` (`OLLAMA_API_KEY=...`) — never in source or committed config.

```python
import os
from openai import OpenAI

client = OpenAI(base_url="https://ollama.com/v1", api_key=os.environ["OLLAMA_API_KEY"])
resp = client.chat.completions.create(
    model="minimax-m3:cloud",
    messages=[{"role": "system", "content": persona_prompt}, *transcript_msgs],
    stream=True,
)
```

Caveats: the cloud OpenAI layer is a subset — no stateful responses, no `n`/`tool_choice`/`logit_bias`, and context size is set via Modelfile, not the API. `minimax-m2:cloud` was retired (replaced by `minimax-m3:cloud`); confirm the live tag before building with `curl -H "Authorization: Bearer $OLLAMA_API_KEY" https://ollama.com/api/tags`. Bids reuse the same model with a short cheap prompt.

## Character builder (tab)

Form to create/edit one persona: name, voice model (upload `.onnx` + `.onnx.json`, or pick existing), `speaker_id`, `length_scale`, system prompt/personality, `eagerness` (0–1 bid bias), `max_words`, color/avatar. A **Preview** button synthesizes a test line in that voice so you can hear it before saving. Persisted to `characters`; voices copied into `models/voices/`. Characters are global and reusable across rooms.

## Rooms (tab)

A room = name + ordered list of character ids + settings (safe word, interjection behavior, max context lines, bid threshold). Full CRUD, and add as many as you want. Characters are shared, so Room 1 = A + B and Room 2 = A + C both reference the same A. "Enter" opens the Live room.

## Live room

- **Kickoff**: type a topic, or hold-to-talk the mic (faster-whisper transcribes it). Either seeds the transcript as `You:`.
- **Loop** (over the room WebSocket): server runs bidding, picks the next speaker, generates the line, streams text to the UI and TTS audio to the browser, appends to transcript, repeats. No turn cap, no auto wrap-up — it runs until you stop it.
- **Controls**: **Play** (start or resume), **Pause** (finish the current line, then hold), **Stop** (end session, save transcript). Resume replays nothing — it continues from the saved transcript.
- **Interject** anytime by mic or text; it becomes the next transcript line and the agents react. On your speech, duck or cut the current playback (configurable).
- **Safe word** (optional, per room): a spoken phrase that triggers Stop.

## Turn-taking — bidding

After each line, poll every character except the last speaker: "how much do you want to speak next, 0–10, as JSON." Score = `bid + eagerness*k + jitter − recency_penalty + direct_address_bonus`; highest speaks. If all bids are low, the top bid still speaks (keeps it moving) or a random persona is nudged to change topic. **Pipeline**: generate line N+1 while line N is still playing, so there is no dead air; discard the pre-generated line if you interject. For long sessions, keep the last \~30 lines verbatim and roll older ones into a running summary refreshed every \~20 turns; add a drift nudge if recent lines get repetitive.

## FastAPI surface

| Method | Path | Purpose |
| --- | --- | --- |
| GET/POST/PUT/DELETE | `/api/characters[/{id}]` | Character CRUD |
| POST | `/api/characters/{id}/preview` | Synthesize a test line, return audio |
| POST | `/api/characters/{id}/voice` | Upload `.onnx` + `.onnx.json` |
| GET/POST/PUT/DELETE | `/api/rooms[/{id}]` | Room CRUD + membership |
| POST | `/api/rooms/{id}/session` | Create or resume a session |
| GET | `/api/sessions/{id}/transcript` | Fetch/export transcript |
| WS | `/ws/rooms/{id}` | Live loop |

WebSocket events — server→client: `line` (speaker, text), `audio` (WAV/PCM chunk), `bid` (scores, for a debug panel), `state` (playing/paused/stopped), `error`. Client→server: `start`, `pause`, `stop`, `interject` (text, or transcribed mic).

## Data model (SQLite)

- `characters(id, name, voice_path, voice_config_path, speaker_id, length_scale, system_prompt, eagerness, max_words, color)`
- `rooms(id, name, safe_word, settings_json)`
- `room_members(room_id, character_id, position)`
- `sessions(id, room_id, status, started_at)`
- `lines(id, session_id, speaker, text, audio_path, bid_json, ts)`

## Repo layout

```
voice-room/
  app/main.py        # FastAPI app + REST routes
  app/ws.py          # room session WebSocket loop
  app/llm.py         # Ollama Cloud client
  app/tts.py         # Piper ONNX synthesis
  app/stt.py         # faster-whisper + silero VAD
  app/bidding.py     # bid poll + speaker selection
  app/memory.py      # transcript + rolling summary
  app/db.py          # SQLite
  app/models.py      # pydantic + row schemas
  web/               # characters / rooms / live views
  models/voices/     # .onnx voice files
  .env               # OLLAMA_API_KEY
  config.yaml
  requirements.txt
```

## Milestones

1. DB + character CRUD + voice upload + preview synth.
2. Room CRUD + membership.
3. Live room, text-only: bidding loop over WS, play/pause/stop/resume, text kickoff.
4. Piper TTS streaming to the browser + pipelining.
5. Mic: browser capture → faster-whisper → kickoff and interject; safe word.
6. Rolling summary + drift nudge; transcript export; optional full-session recording.

## Open questions

- Browser-side audio (mic + playback in the page) vs server-side `sounddevice` — browser is the better fit for a web UI; confirm.
- Frontend: plain JS/htmx or React?
- On your interjection, should agents cut off mid-sentence or finish the current line?
- Confirm the live Ollama model tag via `/api/tags` (`minimax-m3:cloud` assumed).
