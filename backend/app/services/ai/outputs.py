"""Validated structured AI outputs (Pydantic — provider text never trusted raw)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LeadSummary(BaseModel):
    """Advisory summary of one lead for staff follow-up."""

    model_config = {"extra": "forbid"}

    summary: str = Field(min_length=1, max_length=1000)
    key_points: list[str] = Field(default_factory=list, max_length=8)
    suggested_next_step: str = Field(default="", max_length=500)
    confidence: Literal["low", "medium", "high"] = "low"
    provider: str = Field(default="", max_length=64)


class LeadClassification(BaseModel):
    """Advisory classification (never auto-applied to the database)."""

    model_config = {"extra": "forbid"}

    category: Literal["hot", "warm", "cold", "spam_like"] = "cold"
    priority: Literal["low", "medium", "high"] = "low"
    reason: str = Field(default="", max_length=500)
    provider: str = Field(default="", max_length=64)


class CustomerInsight(BaseModel):
    """Advisory customer note for staff (future blocks may surface it)."""

    model_config = {"extra": "forbid"}

    headline: str = Field(min_length=1, max_length=300)
    observations: list[str] = Field(default_factory=list, max_length=8)
    suggested_action: str = Field(default="", max_length=500)
    provider: str = Field(default="", max_length=64)


class OperationalRecommendation(BaseModel):
    """Advisory operational suggestion (never executed automatically)."""

    model_config = {"extra": "forbid"}

    recommendation: str = Field(min_length=1, max_length=500)
    rationale: str = Field(default="", max_length=500)
    expected_impact: Literal["low", "medium", "high"] = "low"
    provider: str = Field(default="", max_length=64)
