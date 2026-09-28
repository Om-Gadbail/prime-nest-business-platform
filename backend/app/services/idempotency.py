"""Idempotency for public mutating requests (Idempotency-Key header).

Contract:
- Key: 8..64 chars, ``[A-Za-z0-9-_]``. Invalid => 422 (client bug, safe).
- Same key + same payload => replay the stored response (same status+body).
- Same key + materially different payload => 409 (never silent overwrite).
- Same key while the first request is in flight => 409 (retry shortly).
- Safety under concurrency comes from the DB unique constraint
  (``uq_idempotency_scope_key``) + SAVEPOINT retry, not app memory.

Retention: rows older than ``IDEMPOTENCY_RETENTION_DAYS`` (default 30)
should be purged by ops tooling via :func:`purge_expired` (Block 8 will own
the scheduler; until then run it manually). Storage stays bounded because
keys are scoped per business+endpoint and old rows are deletable — replays
older than the retention window return 422 asking for a fresh key.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.idempotency import IdempotencyRecord
from app.repositories import idempotency as idem_repo
from app.services.errors import ConflictError

KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
IDEMPOTENCY_RETENTION_DAYS = 30


def validate_key(raw: str | None) -> str | None:
    """Return the stripped key, None when absent, raise ValueError when malformed."""
    if raw is None:
        return None
    key = raw.strip()
    if not key:
        return None
    if not KEY_RE.match(key):
        raise ValueError("Idempotency-Key must be 8..64 characters of [A-Za-z0-9-_].")
    return key


def payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def acquire(
    db: Session,
    *,
    business_id: uuid.UUID,
    endpoint: str,
    idem_key: str | None,
    payload: dict,
) -> tuple[IdempotencyRecord | None, dict | None, int | None]:
    """Claim the key or resolve a replay.

    Returns (record, replay_body, replay_status):
    - (record, None, None): caller owns the key — do the work, then complete().
    - (record, body, status): replay — return body/status WITHOUT side effects.
    - idem_key None: idempotency not requested — (None, None, None).

    Transaction contract: the placeholder is only FLUSHED here, never
    committed (the caller commits once with the business mutation).

    CALLER CONTRACT: call acquire() BEFORE any other write in the
    transaction. On a key conflict the whole transaction is rolled back
    (portable across PostgreSQL and SQLite — savepoints are deliberately
    NOT used here). Rolling back is harmless because only repeatable
    reads precede acquire() in the public intake flow. Concurrency
    safety comes from the DB unique constraint
    (``uq_idempotency_scope_key``), not from app memory.
    """
    if idem_key is None:
        return None, None, None
    digest = payload_hash(payload)
    # Fast path: retry of a finished request replays without any write.
    existing = idem_repo.get_record(
        db, business_id=business_id, endpoint=endpoint, idem_key=idem_key
    )
    if existing is not None:
        if existing.request_hash != digest:
            raise ConflictError(
                "Idempotency-Key was already used with a different payload."
            ) from None
        if existing.response_status is not None and existing.response_body is not None:
            return existing, dict(existing.response_body), int(existing.response_status)
        raise ConflictError(
            "Duplicate request is already being processed. Please retry."
        ) from None
    try:
        record = idem_repo.insert_placeholder(
            db,
            business_id=business_id,
            endpoint=endpoint,
            idem_key=idem_key,
            request_hash=digest,
        )
        db.flush()
        return record, None, None
    except IntegrityError:
        # Lost the insert race: roll back (per the caller contract nothing
        # but reads precede us) and resolve against the winner's row.
        db.rollback()
        return _resolve_conflict(
            db,
            business_id=business_id,
            endpoint=endpoint,
            idem_key=idem_key,
            digest=digest,
        )
    raise AssertionError("unreachable")  # pragma: no cover


def _resolve_conflict(
    db: Session,
    *,
    business_id: uuid.UUID,
    endpoint: str,
    idem_key: str,
    digest: str,
) -> tuple[IdempotencyRecord | None, dict | None, int | None]:
    existing = idem_repo.get_record(
        db, business_id=business_id, endpoint=endpoint, idem_key=idem_key
    )
    if existing is None:  # pragma: no cover - lost race, fail safe
        raise ConflictError(
            "Duplicate request is already being processed. Please retry."
        ) from None
    if existing.request_hash != digest:
        raise ConflictError(
            "Idempotency-Key was already used with a different payload."
        ) from None
    if existing.response_status is not None and existing.response_body is not None:
        return existing, dict(existing.response_body), int(existing.response_status)
    raise ConflictError(
        "Duplicate request is already being processed. Please retry."
    ) from None


def complete(
    db: Session,
    *,
    record: IdempotencyRecord | None,
    response_status: int,
    response_body: dict,
) -> None:
    if record is None:
        return
    idem_repo.complete(
        record, response_status=response_status, response_body=response_body
    )
    db.flush()


def purge_expired(
    db: Session, *, retention_days: int = IDEMPOTENCY_RETENTION_DAYS
) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = idem_repo.delete_older_than(db, cutoff=cutoff)
    db.commit()
    return deleted
