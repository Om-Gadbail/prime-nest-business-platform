"""AIService: the single entry point for AI capabilities.

Guarantees:
- Works with AI_ENABLED=false (raises AIDisabledError; normal flows never
  require AI).
- Provider outputs are validated against Pydantic models BEFORE use; raw
  provider text never mutates the database.
- Advisory only: this service returns suggestions; routers expose them as
  read-only insights. No autonomous actions exist in Block 2.
- Audit: every execution persists metadata (AIRun) — never raw prompts or
  outputs containing customer PII.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.crm_vocab import AI_CAPABILITIES
from app.repositories import ai_runs as runs_repo
from app.services.ai import contexts
from app.services.ai.outputs import (
    CustomerInsight,
    LeadClassification,
    LeadSummary,
    OperationalRecommendation,
)
from app.services.ai.providers import get_provider
from app.services.errors import AIDisabledError, AIProviderError


class AIService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self._settings.ai_enabled)

    @property
    def provider_name(self) -> str:
        return (self._settings.ai_provider or "noop").strip().lower() or "noop"

    @property
    def mode(self) -> str:
        if not self.enabled:
            return "AI_DISABLED"
        if self.provider_name == "noop":
            return "AI_MOCK"
        return "AI_LIVE"

    def require_enabled(self) -> None:
        if not self.enabled:
            raise AIDisabledError(
                "AI is disabled. Set AI_ENABLED=true to use AI insights."
            )

    def _run_structured(
        self,
        db: Session,
        *,
        business_id: uuid.UUID,
        capability: str,
        context: dict[str, Any],
        response_model: type[BaseModel],
        request_id: str = "",
    ) -> BaseModel:
        if capability not in AI_CAPABILITIES:
            raise AIProviderError(f"Unknown AI capability: {capability!r}.")
        self.require_enabled()
        provider = get_provider(self.provider_name)
        started = time.monotonic()
        status = "success"
        error_text = ""
        raw: dict[str, Any] | None = None
        try:
            raw = provider.generate_structured(
                capability=capability,
                context=context,
                response_model=response_model,
                timeout_seconds=self._settings.ai_timeout_seconds,
            )
            if not isinstance(raw, dict):
                raise AIProviderError("Provider returned a non-object response.")
            validated = response_model.model_validate(raw)
        except ValidationError as exc:
            status = "error"
            error_text = f"Provider response failed validation: {exc.errors()}"[:500]
            raise AIProviderError("AI provider returned an invalid response.") from exc
        except AIProviderError as exc:
            status = "error"
            error_text = str(exc)[:500]
            raise
        finally:
            latency_ms = int((time.monotonic() - started) * 1000)
            output_chars = len(str(raw)) if raw is not None else 0
            runs_repo.create_run(
                db,
                business_id=business_id,
                provider=provider.name,
                model=provider.model,
                capability=capability,
                status=status,
                latency_ms=latency_ms,
                input_chars=len(str(context)),
                output_chars=output_chars,
                request_id=(request_id or "")[:64],
                error=error_text,
            )
            db.flush()
        return validated

    def summarize_lead(
        self, db: Session, *, business_id: uuid.UUID, lead: Any, request_id: str = ""
    ) -> LeadSummary:
        context = contexts.build_lead_context(
            lead, max_input_chars=self._settings.ai_max_input_chars
        )
        result = self._run_structured(
            db,
            business_id=business_id,
            capability="lead_summary",
            context=context,
            response_model=LeadSummary,
            request_id=request_id,
        )
        assert isinstance(result, LeadSummary)
        return result

    def classify_lead(
        self, db: Session, *, business_id: uuid.UUID, lead: Any, request_id: str = ""
    ) -> LeadClassification:
        context = contexts.build_lead_context(
            lead, max_input_chars=self._settings.ai_max_input_chars
        )
        result = self._run_structured(
            db,
            business_id=business_id,
            capability="lead_classification",
            context=context,
            response_model=LeadClassification,
            request_id=request_id,
        )
        assert isinstance(result, LeadClassification)
        return result

    def customer_insight(
        self,
        db: Session,
        *,
        business_id: uuid.UUID,
        customer: Any,
        request_id: str = "",
    ) -> CustomerInsight:
        context = contexts.build_customer_context(
            customer, max_input_chars=self._settings.ai_max_input_chars
        )
        result = self._run_structured(
            db,
            business_id=business_id,
            capability="customer_insight",
            context=context,
            response_model=CustomerInsight,
            request_id=request_id,
        )
        assert isinstance(result, CustomerInsight)
        return result

    def operational_recommendation(
        self, db: Session, *, business_id: uuid.UUID, booking: Any, request_id: str = ""
    ) -> OperationalRecommendation:
        context = contexts.build_booking_context(
            booking, max_input_chars=self._settings.ai_max_input_chars
        )
        result = self._run_structured(
            db,
            business_id=business_id,
            capability="operational_recommendation",
            context=context,
            response_model=OperationalRecommendation,
            request_id=request_id,
        )
        assert isinstance(result, OperationalRecommendation)
        return result


def from_settings(settings: Settings) -> AIService:
    return AIService(settings)
