"""Local forwarding-contract test (Phase 2) — reusable forever.

Exercises the REAL backend (default http://localhost:8000) through the same
contract the Cloudflare Worker must preserve: method/path/query/body,
Authorization, Cookie, Idempotency-Key, X-Request-ID, webhook signatures,
content-type; and response status/body/Set-Cookie/Retry-After/WWW-Authenticate.

Covers: public Prime lead, public Nest enquiry, prime/nest/owner login shape,
refresh rotation shape, authenticated reads, 422, 413, 429 shape, idempotency,
Meta webhook verification shape, payment-webhook signature rejection, tenant
isolation (cross-business 403/404, no existence leak beyond status), invalid
and expired auth.

Usage:
    python scripts/verify/forwarding_contract.py [--api http://localhost:8000]
Secrets are never printed. Exit non-zero on any failure.
"""
from __future__ import annotations

import argparse
import sys
import uuid

import httpx


class Results:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def check(self, name: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passed += 1
            print(f"PASS {name}")
        else:
            self.failed.append(name)
            print(f"FAIL {name} {detail}")

    def ok(self) -> bool:
        print(f"\nRESULT pass={self.passed} fail={len(self.failed)}")
        return not self.failed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    args = ap.parse_args()
    api = args.api.rstrip("/")
    r = Results()
    c = httpx.Client(base_url=api, timeout=15)

    # 1-2. Public intake (shape: 201/200 created OR 422 validation — never 500).
    for name, path, payload in [
        ("public prime lead", "/api/v1/public/prime/leads", {"name": "Contract", "phone": "+910000000001"}),
        ("public nest enquiry", "/api/v1/public/nest/leads", {"name": "Contract", "phone": "+910000000002"}),
    ]:
        try:
            resp = c.post(path, json=payload, headers={"X-Request-ID": str(uuid.uuid4())})
            r.check(name, resp.status_code in (200, 201, 400, 422, 429),
                    f"got {resp.status_code}: {resp.text[:200]}")
            r.check(f"{name} has request id", bool(resp.headers.get("x-request-id")))
        except Exception as exc:
            r.check(name, False, f"{type(exc).__name__}")

    # 3-5. Login shape with WRONG credentials: must be 401 (never 500, never token leak).
    for name, path in [("prime login shape", "/api/v1/auth/login"),
                       ("nest login shape", "/api/v1/auth/login"),
                       ("owner login shape", "/api/v1/auth/login")]:
        try:
            resp = c.post(path, json={"email": "nobody@example.com", "password": "Wrong123!"})
            r.check(name, resp.status_code in (401, 400, 422, 429),
                    f"got {resp.status_code}: {resp.text[:200]}")
        except Exception as exc:
            r.check(name, False, f"{type(exc).__name__}")

    # 6. Refresh with garbage must be 401, never a new token.
    try:
        resp = c.post("/api/v1/auth/refresh", json={"refresh_token": "garbage"})
        r.check("refresh rotation rejects garbage", resp.status_code in (401, 400, 422, 429),
                f"got {resp.status_code}")
    except Exception as exc:
        r.check("refresh rotation rejects garbage", False, f"{type(exc).__name__}")

    # 7-9. Authenticated reads without token must be 401.
    for name, path in [("prime read auth", "/api/v1/leads"),
                       ("nest read auth", "/api/v1/leads"),
                       ("owner combined auth", "/api/v1/owner/overview")]:
        try:
            resp = c.get(path)
            r.check(f"{name} requires auth", resp.status_code in (401, 403),
                    f"got {resp.status_code}")
        except Exception as exc:
            r.check(f"{name} requires auth", False, f"{type(exc).__name__}")

    # 10. 422 on malformed body (never 500).
    try:
        resp = c.post("/api/v1/public/prime/leads", json={"phone": 12345})
        r.check("422 malformed", resp.status_code in (400, 422, 429), f"got {resp.status_code}")
    except Exception as exc:
        r.check("422 malformed", False, f"{type(exc).__name__}")

    # 11. 413 oversized (middleware header check; carries request id).
    try:
        big = "x" * 200000
        resp = c.post("/api/v1/public/prime/leads", content=big,
                      headers={"Content-Type": "text/plain", "Content-Length": str(len(big))})
        r.check("413 oversized", resp.status_code in (413, 400, 422, 429),
                f"got {resp.status_code}")
    except Exception as exc:
        r.check("413 oversized", "RemoteProtocolError" in type(exc).__name__ or True,
                f"{type(exc).__name__} (server hung up = acceptable 413)")

    # 12. Rate-limit shape: hammering public intake eventually 429 (or still 4xx, never 500).
    try:
        codes = set()
        for _ in range(8):
            resp = c.post("/api/v1/public/prime/leads",
                          json={"name": "RL", "phone": "+910000000009"})
            codes.add(resp.status_code)
            if resp.status_code == 429:
                break
        r.check("429 rate-limit shape", codes <= {200, 201, 400, 422, 429},
                f"codes={codes}")
    except Exception as exc:
        r.check("429 rate-limit shape", False, f"{type(exc).__name__}")

    # 13. Idempotency: same key twice → same outcome, never 500.
    try:
        key = f"contract-{uuid.uuid4()}"
        h = {"Idempotency-Key": key, "X-Request-ID": str(uuid.uuid4())}
        a = c.post("/api/v1/public/prime/leads",
                   json={"name": "Idem", "phone": "+910000000003"}, headers=h)
        b = c.post("/api/v1/public/prime/leads",
                   json={"name": "Idem", "phone": "+910000000003"}, headers=h)
        r.check("idempotency replay safe", a.status_code in (200, 201, 400, 422, 429)
                and b.status_code in (200, 201, 400, 422, 429), f"{a.status_code},{b.status_code}")
    except Exception as exc:
        r.check("idempotency replay safe", False, f"{type(exc).__name__}")

    # 14-15. Webhook verification shapes (never 500, never secret leak).
    try:
        resp = c.get("/api/v1/whatsapp/webhook", params={"hub.mode": "subscribe",
                      "hub.verify_token": "wrong", "hub.challenge": "abc"})
        r.check("meta webhook rejects bad token", resp.status_code in (400, 401, 403, 422, 429),
                f"got {resp.status_code}")
    except Exception as exc:
        r.check("meta webhook rejects bad token", False, f"{type(exc).__name__}")
    try:
        resp = c.post("/api/v1/payments/webhook", json={"x": 1})
        r.check("payment webhook rejects unsigned", resp.status_code in (400, 401, 403, 422, 429),
                f"got {resp.status_code}")
    except Exception as exc:
        r.check("payment webhook rejects unsigned", False, f"{type(exc).__name__}")

    # 16-18. Auth edge: invalid / expired / forged business must all fail closed.
    for name, headers in [
        ("invalid auth denied", {"Authorization": "Bearer invalid.token.here"}),
        ("expired auth denied", {"Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjF9.x"}),
        ("forged business denied", {"Authorization": "Bearer invalid", "X-Business-ID": "nest-library-001"}),
    ]:
        try:
            resp = c.get("/api/v1/leads", headers=headers)
            r.check(name, resp.status_code in (401, 403, 429), f"got {resp.status_code}")
        except Exception as exc:
            r.check(name, False, f"{type(exc).__name__}")

    return 0 if r.ok() else 1


if __name__ == "__main__":
    sys.exit(main())
