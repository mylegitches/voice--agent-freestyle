from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx
from openai import AsyncOpenAI

from .config import Settings, get_settings


class LLMNotConfigured(RuntimeError):
    pass


class OllamaLLM:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: AsyncOpenAI | None = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.ollama_api_key)

    def _get_client(self) -> AsyncOpenAI:
        if not self.settings.ollama_api_key:
            raise LLMNotConfigured("OLLAMA_API_KEY is not configured")
        if self._client is None:
            self._client = AsyncOpenAI(
                base_url=self.settings.llm_base_url,
                api_key=self.settings.ollama_api_key,
                timeout=self.settings.llm_timeout_seconds,
                max_retries=1,
            )
        return self._client

    async def verify_model(self) -> tuple[bool, str]:
        if not self.settings.ollama_api_key:
            return False, "OLLAMA_API_KEY is not configured"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    "https://ollama.com/api/tags",
                    headers={"Authorization": f"Bearer {self.settings.ollama_api_key}"},
                )
                response.raise_for_status()
                payload = response.json()
            rows = payload if isinstance(payload, list) else payload.get("models", [])
            names = {
                item.get("name") or item.get("model")
                for item in rows
                if isinstance(item, dict)
            }
            if self.settings.llm_model in names:
                return True, f"{self.settings.llm_model} is available"
            return False, f"{self.settings.llm_model} was not returned by Ollama tags"
        except Exception as exc:
            return False, f"Could not verify Ollama model: {exc}"

    async def bid(
        self,
        *,
        name: str,
        personality: str,
        summary: str,
        transcript: str,
    ) -> float:
        client = self._get_client()
        response = await client.chat.completions.create(
            model=self.settings.llm_model,
            temperature=0.2,
            max_tokens=24,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are {name}. {personality}\n"
                        "Decide how strongly you want to speak next. Return only "
                        'JSON in the form {"bid": 0}, using an integer from 0 to 10.'
                    ),
                },
                {
                    "role": "user",
                    "content": f"Conversation summary:\n{summary or '(none)'}\n\nRecent lines:\n{transcript}",
                },
            ],
        )
        content = response.choices[0].message.content or ""
        try:
            match = re.search(r"\{.*?\}", content, flags=re.DOTALL)
            payload: dict[str, Any] = json.loads(match.group(0) if match else content)
            return max(0.0, min(10.0, float(payload["bid"])))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            number = re.search(r"\b(10|[0-9])\b", content)
            return float(number.group(1)) if number else 5.0

    async def stream_line(
        self,
        *,
        name: str,
        personality: str,
        max_words: int,
        summary: str,
        transcript: str,
        drift_nudge: bool,
    ) -> AsyncIterator[str]:
        client = self._get_client()
        nudge = (
            " Change the angle or move the conversation forward; avoid repeating recent openings."
            if drift_nudge
            else ""
        )
        stream = await client.chat.completions.create(
            model=self.settings.llm_model,
            temperature=0.85,
            stream=True,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are {name}. Stay fully in character.\n{personality}\n"
                        f"Speak one natural turn of at most {max_words} words. "
                        "Do not prefix your answer with your name and do not narrate actions."
                        f"{nudge}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Conversation summary:\n{summary or '(none)'}\n\n"
                        f"Recent transcript:\n{transcript}\n\nReply as {name}."
                    ),
                },
            ],
        )
        async for chunk in stream:
            content = chunk.choices[0].delta.content if chunk.choices else None
            if content:
                yield content

    async def summarize(self, previous: str, transcript: str) -> str:
        client = self._get_client()
        response = await client.chat.completions.create(
            model=self.settings.llm_model,
            temperature=0.1,
            max_tokens=350,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Maintain a compact factual conversation memory. Preserve names, "
                        "decisions, running jokes, disagreements, and unresolved questions."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Previous memory:\n{previous or '(none)'}\n\nLines to fold in:\n{transcript}",
                },
            ],
        )
        return (response.choices[0].message.content or previous).strip()


llm_service = OllamaLLM()
