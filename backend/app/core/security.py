"""Low-level security primitives: passwords, JWT, refresh tokens.

- Passwords: Argon2id via pwdlib (never SHA256 / custom hashing).
- JWT: short-lived signed access tokens (minimal claims).
- Refresh: opaque cryptographically-random tokens; only SHA-256 hash stored.
- No logging of secrets happens here; callers must not log return values.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

_password_hash = PasswordHash.recommended()

REFRESH_TOKEN_BYTES = 48  # 64-char urlsafe string


# --- passwords ---


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hash.verify(password, password_hash)
    except Exception:
        return False


def validate_password_policy(password: str) -> None:
    """Raise ValueError on weak passwords. No silent truncation."""
    if not isinstance(password, str):
        raise ValueError("Password must be a string.")
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters long.")
    if len(password) > 128:
        raise ValueError("Password must be at most 128 characters long.")


# --- JWT access tokens ---


def create_access_token(
    *,
    user_id: uuid.UUID | str,
    business_id: uuid.UUID | str | None,
    secret: str,
    algorithm: str = "HS256",
    expires_minutes: int = 30,
) -> tuple[str, str, datetime]:
    """Return (token, jti, expires_at). Minimal claims only."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=expires_minutes)
    jti = uuid.uuid4().hex
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "type": "access",
        "business_id": str(business_id) if business_id else None,
    }
    token = jwt.encode(payload, secret, algorithm=algorithm)
    return token, jti, exp


def decode_access_token(*, token: str, secret: str, algorithms: list[str]) -> dict:
    """Decode + verify signature/expiry/type. Raises jwt.PyJWTError on failure."""
    payload = jwt.decode(token, secret, algorithms=algorithms)
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Not an access token.")
    if not payload.get("sub"):
        raise jwt.InvalidTokenError("Missing subject.")
    return payload


# --- refresh tokens ---


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
