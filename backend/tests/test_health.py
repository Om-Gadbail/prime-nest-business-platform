"""1-4: app boots, /health, /ready, and /api/v1 wiring."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.main import create_app


def test_application_starts() -> None:
    app = create_app()
    assert app.title
    routes = {getattr(r, "path", "") for r in app.routes}
    assert "/health" in routes
    assert "/ready" in routes
    # Included routers resolve lazily in app.routes on newer FastAPI, so
    # assert versioned registration via the OpenAPI schema instead.
    assert "/api/v1/version" in app.openapi()["paths"]


def test_health_returns_success(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["env"] == "testing"
    assert "version" in body and "app" in body
    assert resp.headers.get("X-Request-ID")


def test_ready_returns_ready_when_db_up(client: TestClient, db_session_mock: object) -> None:
    client.app.dependency_overrides[get_db] = lambda: db_session_mock  # type: ignore[attr-defined]
    try:
        resp = client.get("/ready")
    finally:
        client.app.dependency_overrides.clear()  # type: ignore[attr-defined]
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"
    assert resp.json()["database"] == "up"


def test_ready_returns_503_when_db_down(client: TestClient) -> None:
    class _FailingSession:
        def execute(self, *args: object, **kwargs: object) -> object:
            raise ConnectionError("db unreachable")

        def close(self) -> None:
            pass

    client.app.dependency_overrides[get_db] = lambda: _FailingSession()  # type: ignore[attr-defined]
    try:
        resp = client.get("/ready")
    finally:
        client.app.dependency_overrides.clear()  # type: ignore[attr-defined]
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"
    assert resp.json()["database"] == "down"


def test_api_version_responds(client: TestClient) -> None:
    resp = client.get("/api/v1/version")
    assert resp.status_code == 200
    body = resp.json()
    assert body["api_version"] == "v1"
    assert body["env"] == "testing"
