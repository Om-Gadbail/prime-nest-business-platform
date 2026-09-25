"""6: database connection handling (unit-level, no live DB required)."""

from __future__ import annotations

from app.core import database
from app.repositories import health as health_repo


def test_ping_database_returns_false_when_unreachable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class _BadEngine:
        def connect(self, *a: object, **k: object) -> object:
            raise ConnectionError("unreachable")

    monkeypatch.setattr(database, "get_engine", lambda: _BadEngine())
    assert database.ping_database() is False


def test_repository_ping_true_on_success(db_session_mock: object) -> None:
    assert health_repo.ping(db_session_mock) is True  # type: ignore[arg-type]


def test_repository_ping_false_on_failure() -> None:
    class _FailingSession:
        def execute(self, *args: object, **kwargs: object) -> object:
            raise ConnectionError("down")

    assert health_repo.ping(_FailingSession()) is False  # type: ignore[arg-type]


def test_get_db_yields_and_closes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    closed = {"v": False}

    class _Session:
        def close(self) -> None:
            closed["v"] = True

    class _Factory:
        def __call__(self) -> _Session:
            return _Session()

    monkeypatch.setattr(database, "get_session_factory", lambda: _Factory())
    gen = database.get_db()
    session = next(gen)
    assert isinstance(session, _Session)
    try:
        next(gen)
    except StopIteration:
        pass
    assert closed["v"] is True
