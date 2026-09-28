"""Idempotency repository: SQL only (uniqueness enforced by constraint)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.idempotency import IdempotencyRecord


def get_record(
    db: Session, *, business_id: uuid.UUID, endpoint: str, idem_key: str
) -> IdempotencyRecord | None:
    stmt = select(IdempotencyRecord).where(
        IdempotencyRecord.business_id == business_id,
        IdempotencyRecord.endpoint == endpoint,
        IdempotencyRecord.idem_key == idem_key,
    )
    return db.execute(stmt).scalars().first()


def insert_placeholder(
    db: Session,
    *,
    business_id: uuid.UUID,
    endpoint: str,
    idem_key: str,
    request_hash: str,
) -> IdempotencyRecord:
    """Insert an in-flight row. Raises IntegrityError on concurrent duplicate."""
    record = IdempotencyRecord(
        business_id=business_id,
        endpoint=endpoint,
        idem_key=idem_key,
        request_hash=request_hash,
        response_status=None,
        response_body=None,
    )
    db.add(record)
    db.flush()  # constraint violation surfaces here, inside the transaction
    return record


def complete(
    record: IdempotencyRecord, *, response_status: int, response_body: dict
) -> IdempotencyRecord:
    record.response_status = response_status
    record.response_body = dict(response_body)
    return record


def delete_older_than(db: Session, *, cutoff: datetime) -> int:
    """Retention cleanup (bounded deletes for ops tooling)."""
    result = db.execute(
        delete(IdempotencyRecord).where(IdempotencyRecord.created_at < cutoff)
    )
    return int(result.rowcount or 0)
