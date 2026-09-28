"""Gemini structured-output adapter for the advisory AIService (Block 10).

Uses the same REST generateContent endpoint as the chat gateway (no vendor
SDK in business logic). Prompts request strict JSON matching the Pydantic
response model; output is validated by AIService BEFORE use. No side
effects. Honest errors when unconfigured (never fake data).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import get_settings
from app.services.ai.providers import AIProvider
from app.services.errors import AIProviderError


class GeminiStructuredProvider(AIProvider):
    name = "gemini"

    def __init__(self) -> None:
        settings = get_settings()
        self.model = (settings.gemini_model or "gemini-2.0-flash").strip()
        self._api_key = (settings.gemini_api_key or "").strip()
        self._timeout = int(settings.ai_timeout_seconds or 20)

    def generate_structured(
        self,
        *,
        capability: str,
        context: dict[str, Any],
        response_model: type[BaseModel],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise AIProviderError("Gemini is not configured (GEMINI_API_KEY missing).")
        schema = response_model.model_json_schema()
        prompt = (
            f"Capability: {capability}. Context (PII-masked): {str(context)[:4000]}. "
            f"Respond with JSON ONLY matching this schema: {json.dumps(schema)[:3000]}."
        )
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self._api_key}"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
        }
        try:
            resp = httpx.post(
                url, json=payload, timeout=float(timeout_seconds or self._timeout)
            )
        except Exception as exc:
            raise AIProviderError(f"Gemini transport failed: {exc}") from exc
        if resp.status_code >= 400:
            raise AIProviderError(f"Gemini request failed (HTTP {resp.status_code}).")
        try:
            data = resp.json()
            candidates = data.get("candidates") or [{}]
            content = candidates[0].get("content") or {}
            parts = content.get("parts") or []
            text = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
            return dict(json.loads(cleaned))
        except Exception as exc:
            raise AIProviderError("Gemini returned an unreadable response.") from exc
