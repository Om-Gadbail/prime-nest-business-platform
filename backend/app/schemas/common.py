"""Shared API contracts: pagination envelope + bounded list params."""

from __future__ import annotations

from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

from app.repositories.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

ItemT = TypeVar("ItemT")


class Page(BaseModel, Generic[ItemT]):
    items: list[ItemT]
    total: int
    limit: int
    offset: int


def list_params(
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=1000000),
    offset: int = Query(default=0, ge=0, le=1000000),
    sort: str | None = Query(default=None, max_length=64),
    direction: str | None = Query(default="desc", max_length=8),
) -> dict:
    direction_clean = (direction or "desc").lower()
    if direction_clean not in ("asc", "desc"):
        direction_clean = "desc"
    # Sane maximum enforced server-side (clamped, never an error).
    return {
        "limit": min(limit, MAX_PAGE_SIZE),
        "offset": offset,
        "sort": sort,
        "direction": direction_clean,
    }
