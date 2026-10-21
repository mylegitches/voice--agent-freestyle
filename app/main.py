from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.characters import router as characters_router
from .api.characters import voices_router
from .api.rooms import router as rooms_router
from .api.sessions import router as sessions_router
from .config import get_settings
from .db import close_db, init_db
from .llm import llm_service
from .stt import stt_service
from .tts import tts_service
from .voice_catalog import voice_catalog
from .ws import router as ws_router


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(title="Voice Agent Room", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(characters_router)
app.include_router(voices_router)
app.include_router(rooms_router)
app.include_router(sessions_router)
app.include_router(ws_router)


@app.get("/api/health")
async def health(verify_llm: bool = Query(default=False)):
    voices = voice_catalog.scan()
    llm_ok = llm_service.configured
    llm_message = "configured" if llm_ok else "OLLAMA_API_KEY is not configured"
    if verify_llm and llm_ok:
        llm_ok, llm_message = await llm_service.verify_model()
    return {
        "status": "ready" if voices else "degraded",
        "voices": {
            "count": len(voices),
            "errors": [voice.id for voice in voices if voice.status == "error"],
            "tts_dependency": tts_service.available(),
        },
        "stt": {"dependency": stt_service.available(), "model": settings.whisper_model},
        "llm": {
            "configured": llm_service.configured,
            "verified": llm_ok if verify_llm else None,
            "model": settings.llm_model,
            "message": llm_message,
        },
    }


if settings.web_dist.exists():
    assets = settings.web_dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        requested = settings.web_dist / path
        if path and requested.is_file():
            return FileResponse(requested)
        return FileResponse(settings.web_dist / "index.html")
else:
    @app.get("/", include_in_schema=False)
    async def root():
        return {
            "name": "Voice Agent Room",
            "message": "Frontend is not built. Run npm install && npm run build in web/.",
            "docs": "/docs",
        }
