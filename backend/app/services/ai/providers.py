"""AI provider interface + Noop provider (Block 2).

Business logic depends only on ``AIProvider.generate_structured``. Adding a
real provider later means: implement the interface (HTTP call with timeout,
structured-output parsing), register it in ``PROVIDERS``, set AI_PROVIDER +
credentials in backend env. No router/service changes needed.
"""

from __future__ import annotations

import abc
from typing import Any

from pydantic import BaseModel

from app.services.errors import AIProviderError


class AIProvider(abc.ABC):
    """Provider-neutral contract for structured AI capabilities."""

    name: str = "abstract"
    model: str = ""

    @abc.abstractmethod
    def generate_structured(
        self,
        *,
        capability: str,
        context: dict[str, Any],
        response_model: type[BaseModel],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        """Return a dict that validates against ``response_model``.

        Must raise AIProviderError (never leak SDK internals) on failure.
        Must never perform side effects (advisory only).
        """


class NoopProvider(AIProvider):
    """Deterministic mock for development/tests. Never presented as real AI.

    Every output carries ``provider="noop"`` so UIs can label it honestly.
    """

    name = "noop"
    model = "noop-deterministic-v1"

    def generate_structured(
        self,
        *,
        capability: str,
        context: dict[str, Any],
        response_model: type[BaseModel],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        status = str(context.get("status", "new"))
        interest = str(context.get("service_interest", "") or "general enquiry")
        name = str(context.get("display_name", "") or "this lead")
        if capability == "lead_summary":
            return {
                "summary": (
                    f"Mock summary for {name}: status {status}, "
                    f"interested in {interest}. (Noop provider — not real AI.)"
                ),
                "key_points": [f"Status: {status}", f"Interest: {interest}"],
                "suggested_next_step": "Contact the lead on their preferred channel.",
                "confidence": "low",
                "provider": "noop",
            }
        if capability == "lead_classification":
            return {
                "category": "warm" if status in ("new", "contacted") else "cold",
                "priority": "medium" if status == "new" else "low",
                "reason": "Deterministic mock classification (noop provider).",
                "provider": "noop",
            }
        if capability == "customer_insight":
            return {
                "headline": "Mock customer insight (noop provider — not real AI).",
                "observations": [],
                "suggested_action": "Review the customer record manually.",
                "provider": "noop",
            }
        if capability == "operational_recommendation":
            return {
                "recommendation": "Mock recommendation (noop provider — not real AI).",
                "rationale": "Deterministic placeholder.",
                "expected_impact": "low",
                "provider": "noop",
            }
        raise AIProviderError(f"Noop provider has no capability: {capability!r}.")


PROVIDERS: dict[str, type[AIProvider]] = {
    NoopProvider.name: NoopProvider,
    "gemini": NoopProvider,  # resolved lazily below to avoid import cycles
}


def get_provider(name: str) -> AIProvider:
    """Instantiate a registered provider (clear error for unknown names)."""
    key = str(name or "").strip().lower() or "noop"
    if key == "gemini":
        # Structured-output Gemini adapter: real HTTP call when GEMINI_API_KEY
        # is configured, honest error otherwise (never fake data).
        from app.services.ai.gemini_structured import GeminiStructuredProvider

        return GeminiStructuredProvider()
    factory = PROVIDERS.get(key)
    if factory is None:
        raise AIProviderError(
            f"Unknown AI provider: {name!r}. "
            f"Available: {sorted(PROVIDERS)}. "
            "External providers are a future integration (backend env only)."
        )
    return factory()
