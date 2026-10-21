# Voice Agent Room — Implementation Plan

## 1. Outcome

Build a local-first web application where the user can:

1. Create reusable characters from a Piper voice and a personality prompt.
2. Arrange characters into reusable rooms.
3. Start a room from typed text or push-to-talk audio.
4. Let characters converse continuously, with visible turn bids and queued audio.
5. Pause, resume, interject, stop, and export the saved transcript.

The first releasable version is a reliable single-user application bound to
`127.0.0.1`. It does not need accounts, remote collaboration, or deployment.

## 2. Decisions Locked for the Initial Build

- **Frontend:** React + TypeScript + Vite. The live-room state machine, audio
  queue, reconnect behavior, and three editing views justify a typed UI.
- **Audio ownership:** the browser captures the microphone and plays all agent
  audio. The server never opens a system audio device.
- **Interjection behavior:** immediately stop/duck current browser playback,
  cancel any queued or speculative response, transcribe/append the user's line,
  then resume agent turns.
- **LLM:** one `AsyncOpenAI` client pointed at Ollama Cloud; all characters use
  the configured model tag, with personality supplied only through prompts.
- **TTS:** Piper models are loaded lazily on first use and cached for the life of
  the process. Synthesis runs outside the event loop.
- **Audio delivery:** synthesize one complete WAV per utterance and send it as a
  binary WebSocket frame associated with a line id. Generate the next line while
  the current WAV is playing. True partial-utterance PCM streaming is deferred
  until profiling proves it is needed.
- **Persistence:** SQLite via SQLAlchemy 2.x with Alembic migrations.
- **One live owner per room:** one active session loop and one controlling
  WebSocket per room. A second connection may observe later, but multi-controller
  behavior is out of scope for v1.
- **Source assets:** existing `models/*.onnx` files remain untouched. The app
  discovers both the current flat `models/` directory and the canonical
  `models/voices/` upload directory.
- **Git policy:** model binaries, generated audio, the database, and `.env` are
  runtime data and are ignored. If model distribution is later required, adopt
  Git LFS deliberately rather than committing large ONNX files normally.

## 3. Proposed Repository Layout

```text
app/
  api/
    characters.py
    rooms.py
    sessions.py
  main.py
  config.py
  db.py
  models.py
  repositories.py
  ws.py
  session_manager.py
  bidding.py
  llm.py
  tts.py
  stt.py
  memory.py
  voice_catalog.py
web/
  src/
    api/
    components/
    hooks/
    views/CharactersView.tsx
    views/RoomsView.tsx
    views/LiveRoomView.tsx
    audio/
    types.ts
    App.tsx
  index.html
tests/
  unit/
  integration/
  fixtures/
models/
  voices/                 # uploaded voices; existing flat models also discovered
data/
  voice-room.sqlite3
  sessions/<session-id>/  # optional saved utterance WAV files
alembic/
.env.example
.gitignore
config.yaml
requirements.txt
README.md
```

## 4. Runtime Architecture

```text
React UI
  ├─ REST: character, room, session, transcript, preview
  └─ WebSocket: control events, streamed text events, binary WAV messages
         │
FastAPI application
  ├─ SessionManager: one task/state machine per active room
  ├─ Async Ollama client: bids, responses, summaries
  ├─ Piper cache: ONNX voice sessions + synthesis worker pool
  ├─ Whisper service: user microphone only
  └─ SQLite: configuration, sessions, transcript metadata
```

The session state machine is explicit:

```text
IDLE → PLAYING → PAUSE_REQUESTED → PAUSED → PLAYING
            └──────────────────────────────→ STOPPING → STOPPED
```

`pause` completes the current character line before entering `PAUSED`.
`interject` is higher priority: it invalidates the current playback/queued turn
using a generation number, appends the user's line, and starts a fresh turn.
`stop` cancels outstanding work, finalizes the session, and persists state.

## 5. API and Message Contracts

Implement the REST surface in the handoff, plus two small discovery endpoints:

- `GET /api/voices` — validated voice/config pairs and compatibility status.
- `GET /api/health` — database, model configuration, and optional dependency
  readiness without exposing secrets.

Use JSON WebSocket messages for control and metadata. Suggested server events:

- `state`: session id, state, reason, monotonically increasing revision.
- `bid`: candidates, raw bid, adjusted score, winner, and turn id.
- `line_start`: line id, speaker, color, turn id.
- `line_delta`: incremental LLM text for display.
- `line_final`: canonical saved text and word count.
- `audio_start`: line id, MIME type, byte length, sample rate.
- binary frame: the WAV payload for the preceding `audio_start`.
- `transcription`: user text and whether the safe word matched.
- `error`: stable code, recoverable flag, and user-safe message.

Client events:

- `start`, `pause`, `stop`, `interject_text`.
- `mic_start`, binary microphone chunks, `mic_end`.
- `playback_started`, `playback_finished`, `playback_cancelled`; these let the
  server pipeline the next turn without guessing browser playback timing.

Every event that changes state carries a client command id. Duplicate commands
are ignored, making reconnect/retry safe.

## 6. Voice Asset Handling

The repository currently contains eleven ONNX/config pairs. All report 22,050 Hz
audio and appear to be single-speaker voices; ten configs expose the expected
language/speaker metadata. The GLaDOS config omits at least some optional metadata,
so discovery will default a missing speaker count to one and a missing language to
`unknown` instead of rejecting the model.

Before exposing a voice as usable, `voice_catalog.py` will:

1. Match `.onnx` with the exact `.onnx.json` sibling.
2. Validate paths stay inside an allowed model root.
3. Parse sample rate, speaker count, inference defaults, and language defensively.
4. Confirm the requested `speaker_id` is valid; single-speaker voices use `0`.
5. Run an explicit load/synthesis smoke test on demand and cache the result.

Uploads are written to a temporary file, size-checked, validated, then atomically
moved into `models/voices/`. Replacing a voice invalidates its cached TTS session.

## 7. Prompt and Turn-Taking Design

Keep prompt construction centralized and deterministic.

### Bid prompt

Each eligible character receives its personality, the running summary, recent
lines, and a request for one integer from 0–10 in a tiny JSON object. Parse JSON
defensively, clamp the result, apply a short timeout, and fall back to a neutral
bid when a response is invalid.

Adjusted score:

```text
raw_bid
+ eagerness * eagerness_weight
+ bounded random jitter
- recency penalty
+ direct-address bonus
```

Poll eligible characters concurrently with a small concurrency/rate limit. Log
both raw and adjusted values for the optional debug panel.

### Line prompt

Provide the selected character's immutable system personality, room rules,
rolling summary, recent verbatim transcript, and a strict `max_words` request.
Stream text to the UI, but persist only the final normalized line. If output is
too long, prefer a follow-up shortening pass over cutting text mid-sentence.

### Memory

- Keep the latest configured number of lines verbatim (default 30).
- Refresh the running summary after each configured interval (default 20 turns).
- Preserve names, decisions, unresolved questions, and topic changes.
- Detect repeated openings or high lexical overlap and add a one-turn drift nudge.
- Summarization failure never stops the conversation; retain the previous summary.

## 8. Delivery Milestones

### Milestone 0 — Foundation and compatibility gate

- Create the Python and web projects, configuration loader, structured logging,
  `.env.example`, `.gitignore`, and one-command development scripts.
- Validate Python/ONNX/CTranslate2 compatibility on the target Windows machine.
- Discover all eleven local voice pairs and smoke-test at least one ordinary model
  plus the metadata-light GLaDOS model.
- With `OLLAMA_API_KEY` present, query the authenticated Ollama tags endpoint and
  record the selected live model in `config.yaml`; fail startup clearly if absent.

**Exit:** backend and frontend start locally; health endpoint distinguishes
configured, degraded, and unavailable optional services.

### Milestone 1 — Characters and voice preview

- Add schema/migration, repository, validation, and full character CRUD.
- Add the voice catalog, secure paired upload, and cached Piper service.
- Build the Characters view with create/edit/delete and preview playback.

**Exit:** a user can create a character from any discovered voice, reload the app,
edit it, and hear a preview without restarting the server.

### Milestone 2 — Rooms

- Add room and ordered membership persistence with transactional updates.
- Build room CRUD, character ordering, settings, and validation requiring at least
  two usable characters before entry.

**Exit:** shared characters can participate in multiple independently configured
rooms, and ordering survives reload.

### Milestone 3 — Text-only live room

- Add sessions/lines persistence and `SessionManager`.
- Implement WebSocket lifecycle, bidding, LLM streaming, and typed kickoff/interject.
- Implement play, finish-current-line pause, resume, stop, reconnect snapshot, and
  the bid debug panel.
- Use fake deterministic LLM fixtures for integration tests.

**Exit:** a room can run indefinitely in text mode and recover cleanly from a page
reload without duplicate turns.

### Milestone 4 — TTS and pipelining

- Synthesize final lines with the selected warm Piper model.
- Add binary WAV protocol and a browser audio queue.
- Generate/synthesize turn N+1 during playback of turn N, gated by browser playback
  acknowledgements. Invalidate speculative work on interjection or stop.
- Make playback failure visible but non-fatal to transcript generation.

**Exit:** continuous conversations have no avoidable dead air, voices match their
characters, and pause/stop/interject never play stale queued audio.

### Milestone 5 — Microphone, transcription, and safe word

- Add push-to-talk capture with visible permission and recording states.
- Send captured audio over the room WebSocket and transcribe in a worker.
- Apply VAD before Whisper, normalize the transcript, and match the safe word on
  word boundaries with case/punctuation tolerance.
- Abort browser playback immediately when an interjection begins.

**Exit:** microphone kickoff/interjection works in a supported browser, silence is
handled gracefully, and the configured safe word reliably stops the session.

### Milestone 6 — Long-session hardening and export

- Add rolling summary, context budgeting, drift detection, transcript export, and
  cleanup/retention settings for generated audio.
- Add cancellation, timeout, retry/backoff, and rate-limit handling around cloud
  calls; never retry a stopped or superseded turn.
- Run a long-session soak test and document resource usage.

**Exit:** a multi-hour session stays responsive, bounded in context/disk growth,
and exports a complete transcript.

## 9. Test Strategy

- **Unit:** score calculation, recency/direct-address rules, safe-word matching,
  config parsing, context trimming, summary refresh, state transitions.
- **Repository/API:** CRUD constraints, membership ordering, session resume,
  uploads, traversal rejection, transcript export.
- **WebSocket integration:** use fake LLM/TTS/STT services to test sequencing,
  idempotency, pause boundaries, cancellation, reconnect, and binary audio mapping.
- **Voice compatibility:** load each local pair and synthesize a short sentence;
  keep this as an opt-in hardware/runtime test rather than a normal fast test.
- **Browser end-to-end:** Chromium tests for character/room flows, playback queue,
  text live room, reconnect, and mocked microphone capture.
- **Manual acceptance:** real Ollama credentials, all voices, microphone permission,
  long-running conversation, safe word, and transcript export.

No normal test suite should spend cloud tokens. Real-provider tests are explicitly
marked and opt-in.

## 10. Failure and Safety Rules

- Bind locally by default and never return secrets through API responses or logs.
- Validate upload extension, size, paired basename, JSON shape, and final path.
- Serialize database writes that belong to one turn.
- Keep transcript text even if synthesis or playback fails.
- A malformed bid becomes a fallback score, not a dead room.
- A failed character response retries once with bounded backoff, then emits a
  recoverable error and selects another character.
- Stop and interjection increment the generation number; late task results with an
  older generation are discarded before persistence or playback.
- On WebSocket loss, keep the room paused for a short reconnect grace period, then
  pause durably rather than allowing an unattended cloud loop to spend tokens.

## 11. Configuration Defaults

```yaml
server:
  host: 127.0.0.1
  port: 8000
llm:
  base_url: https://ollama.com/v1
  model: minimax-m3  # authenticated tag verified on 2026-10-21
room_defaults:
  max_context_lines: 30
  summary_interval: 20
  bid_threshold: 3
  eagerness_weight: 2.0
  direct_address_bonus: 3.0
  interjection_mode: cut
audio:
  save_session_audio: false
  model_roots:
    - models
    - models/voices
```

Secrets belong only in `.env`; checked-in configuration contains no API key.

## 12. Build Order and Review Checkpoints

Implement milestones in order. At the end of each milestone:

1. Run automated tests and the relevant manual smoke test.
2. Update README setup/troubleshooting instructions.
3. Commit a small, runnable vertical slice.
4. Demo the user-visible behavior before starting the next risky integration.

The most important early checkpoint is Milestone 0. Piper, ONNX Runtime,
CTranslate2, microphone encoding, and the authenticated Ollama tag are environment
dependent; proving those paths first prevents the UI and data model from being
built around an invalid runtime assumption.
