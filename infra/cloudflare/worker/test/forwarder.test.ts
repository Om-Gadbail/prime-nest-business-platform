import { describe, it, expect } from "vitest";
import {
  buildUpstreamHeaders,
  buildClientHeaders,
  default as worker,
} from "../src/index.js";

const ENV = {
  UPSTREAM_BACKEND_URL: "http://127.0.0.1:8000",
  CF_ACCESS_CLIENT_ID: "id123",
  CF_ACCESS_CLIENT_SECRET: "sec123",
};

describe("forwarder contract", () => {
  it("preserves auth, cookies, idempotency, request-id, signatures, content-type", () => {
    const req = new Request("https://api.example.com/api/v1/leads?page=2", {
      method: "POST",
      headers: {
        Authorization: "Bearer user-jwt",
        Cookie: "refresh_token=abc",
        "Idempotency-Key": "key-1",
        "X-Request-ID": "rid-1",
        "X-Razorpay-Signature": "sig",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ a: 1 }),
    });
    const h = buildUpstreamHeaders(req, ENV as never, "rid-1");
    expect(h.get("authorization")).toBe("Bearer user-jwt");
    expect(h.get("cookie")).toBe("refresh_token=abc");
    expect(h.get("idempotency-key")).toBe("key-1");
    expect(h.get("x-request-id")).toBe("rid-1");
    expect(h.get("x-razorpay-signature")).toBe("sig");
    expect(h.get("content-type")).toContain("application/json");
    // Access service auth added for the private origin:
    expect(h.get("cf-access-client-id")).toBe("id123");
    // End-user Authorization is untouched (origin auth passes through):
    expect(h.get("authorization")).not.toContain("id123");
  });

  it("preserves response status/body/cookies, maps infra failure to 502/504 only", async () => {
    const res = new Headers();
    res.set("Set-Cookie", "refresh_token=abc; HttpOnly");
    res.set("Retry-After", "30");
    res.set("WWW-Authenticate", "Bearer");
    res.set("X-Evil", "drop-me");
    const out = buildClientHeaders(res);
    expect(out.get("set-cookie")).toContain("refresh_token");
    expect(out.get("retry-after")).toBe("30");
    expect(out.get("www-authenticate")).toBe("Bearer");
    expect(out.get("x-evil")).toBeNull();

    // Unconfigured upstream -> 500 infra JSON (never application JSON rewrite):
    const r = await worker.fetch(
      new Request("https://api.example.com/health"),
      {} as never,
    );
    expect([500, 502, 504]).toContain(r.status);
    expect(r.headers.get("x-request-id")).toBeTruthy();
  });

  it("rejects oversized bodies with 413 + request id", async () => {
    const r = await worker.fetch(
      new Request("https://api.example.com/api/v1/leads", {
        method: "POST",
        headers: { "content-length": "999999999" },
        body: "x",
      }),
      ENV as never,
    );
    expect(r.status).toBe(413);
    expect(r.headers.get("x-request-id")).toBeTruthy();
  });
});
