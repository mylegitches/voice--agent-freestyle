# Voice Agent Room

A local voice-persona studio. Build characters from Piper ONNX voices, arrange
them into rooms, and let them hold an ongoing spoken conversation through Ollama
Cloud. You can start or interrupt by text or microphone, pause after the current
line, stop safely, inspect turn bids, and export every transcript.

## Quick start (Windows)

1. Copy `.env.example` to `.env` and put your Ollama Cloud key in it:

   ```dotenv
   OLLAMA_API_KEY=your_key_here
   ```

2. Start the app:

   ```powershell
   .\run.ps1
   ```

3. Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

The checked-in frontend build is served by FastAPI. `run.ps1` creates the Python
environment and builds the frontend if either is missing.

## First room

1. Open **Characters** and make at least two characters. The app discovers the
   eleven voice pairs already present under `models/`.
2. Use **Preview** to verify each voice.
3. Open **Rooms**, create a room, choose the cast order, and optionally set a safe
   word.
4. Enter the room, type a topic, then press Play. Hold the microphone button to
   interrupt. Playback is cut immediately while your speech is transcribed.

## Development

Backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Frontend with hot reload and API/WebSocket proxy:

```powershell
cd web
npm run dev
```

Build and tests:

```powershell
cd web
npm run build
cd ..
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\smoke_voices.py
.\.venv\Scripts\python.exe scripts\smoke_live.py
```

OpenAPI documentation is at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).
`GET /api/health?verify_llm=true` performs an authenticated live model-tag check.
`smoke_live.py` uses a temporary database but makes a few real Ollama calls.

## Data and model policy

- `.env`, SQLite data, generated session audio, and ONNX model binaries are
  ignored by Git.
- Uploaded voices are stored in `models/voices/`.
- Existing flat `models/*.onnx` files are also discovered without being moved.
- The database lives at `data/voice-room.sqlite3` by default.
- The server binds to `127.0.0.1`; it is not exposed to the network unless you
  deliberately change the host.

## Speech behavior

- Piper models are loaded lazily and cached until the server stops.
- faster-whisper is loaded on the first microphone transcription. The first use
  may download the configured `small.en` model and can take longer than later
  transcriptions.
- Browser microphone audio is used only for the user's kickoff/interjections.
  Agents exchange text and never transcribe one another.
- At most two utterances are allowed in the browser audio pipeline. Stop or
  interjection invalidates stale generation and queued playback.

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for architecture, milestones, message
contracts, and acceptance criteria.
