"""Response schemas (Pydantic v2). All outbound payloads are validated here."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
    app: str
    version: str
    env: str


class ReadyResponse(BaseModel):
    status: str = Field(examples=["ready"])
    database: str = Field(examples=["up"])
    app: str
    version: str
    env: str


class NotReadyResponse(BaseModel):
    status: str = Field(examples=["not_ready"])
    database: str = Field(examples=["down"])
    app: str
    version: str
    env: str


class VersionResponse(BaseModel):
    api_version: str = Field(examples=["v1"])
    app: str
    version: str
    env: str


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
