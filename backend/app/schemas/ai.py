"""AI endpoint schemas (advisory insights + mode reporting)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.ai.outputs import (
    CustomerInsight,
    LeadClassification,
    LeadSummary,
    OperationalRecommendation,
)


class AIModeOut(BaseModel):
    enabled: bool
    mode: str
    provider: str
    capabilities: list[str] = Field(default_factory=list)


class LeadSummaryOut(BaseModel):
    mode: str
    insight: LeadSummary


class LeadClassificationOut(BaseModel):
    mode: str
    insight: LeadClassification


class CustomerInsightOut(BaseModel):
    mode: str
    insight: CustomerInsight


class OperationalRecommendationOut(BaseModel):
    mode: str
    insight: OperationalRecommendation
