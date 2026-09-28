"""AI run audit repository: SQL only (metadata, never prompts/outputs)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.ai_run import AIRun


def create_run(
    db: Session,
    *,
    business_id: uuid.UUID,
    provider: str,
    model: str,
    capability: str,
    status: str,
    latency_ms: int | None,
    input_chars: int,
    output_chars: int | None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    request_id: str = "",
    error: str = "",
) -> AIRun:
    run = AIRun(
        business_id=business_id,
        provider=provider,
        model=model,
        capability=capability,
        status=status,
        latency_ms=latency_ms,
        input_chars=input_chars,
        output_chars=output_chars,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        request_id=request_id,
        error=error,
    )
    db.add(run)
    db.flush()
    return run
