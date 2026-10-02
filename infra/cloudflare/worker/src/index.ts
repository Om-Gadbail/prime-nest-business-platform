/**
 * Prime x Nest API forwarder — tiny TypeScript Cloudflare Worker.
 *
 * Architecture: Pages -> THIS WORKER -> Cloudflare Access -> Tunnel -> VPS FastAPI -> Neon.
 * This worker holds NO database credentials, NO business logic, NO auth/RBAC,
 * NO tenant resolution. It is a pure HTTP forwarder that preserves the
 * application contract end to end.
 *
 * Preserved request: METHOD, PATH, QUERY, BODY, Authorization, Cookie,
 *   Idempotency-Key, X-Request-ID, webhook signatures, Content-Type.
 * Preserved response: status, body, Set-Cookie, Retry-After,
 *   WWW-Authenticate, safe headers.
 * Infrastructure failures only -> 502/504. Application JSON is never rewritten.
 *
 * Secrets (wrangler secret put, never in Git):
 *   UPSTREAM_BACKEND_URL, CF_ACCESS_CLIENT_ID, CF_ACCESS_CLIENT_SECRET
 */

export interface Env {
  UPSTREAM_BACKEND_URL: string;
  CF_ACCESS_CLIENT_ID?: string;
  CF_ACCESS_CLIENT_SECRET?: string;
  MAX_BODY_BYTES?: string;
  FORWARD_TIMEOUT_MS?: string;
}

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

const SIGNATURE_HEADERS = [
  "x-hub-signature-256",
  "x-hub-signature",
  "x-razorpay-signature",
  "x-meta-signature",
  "stripe-signature",
  "x-request-signature",
];

function requestId(headers: Headers): string {
  const existing = headers.get("x-request-id");
  if (existing && existing.trim()) return existing.trim().slice(0, 128);
  return crypto.randomUUID();
}

function upstreamUrl(env: Env, req: Request): URL {
  const base = (env.UPSTREAM_BACKEND_URL || "").replace(/\/+$/, "");
  if (!base.startsWith("http://") && !base.startsWith("https://")) {
    throw new Error("UPSTREAM_BACKEND_URL is not configured");
  }
  const incoming = new URL(req.url);
  return new URL(incoming.pathname + incoming.search, base + "/");
}

export function buildUpstreamHeaders(req: Request, env: Env, rid: string): Headers {
  const out = new Headers();
  const passthrough = [
    "authorization",
    "cookie",
    "content-type",
    "content-length",
    "accept",
    "accept-language",
    "idempotency-key",
    "x-idempotency-key",
    "retry-after",
    "if-match",
    "if-none-match",
    ...SIGNATURE_HEADERS,
  ];
  for (const name of passthrough) {
    const v = req.headers.get(name);
    if (v !== null) out.set(name, v);
  }
  out.set("x-request-id", rid);
  out.set("x-forwarded-by", "prime-nest-worker");
  const proto = new URL(req.url).protocol.replace(":", "");
  if (proto) out.set("x-forwarded-proto", proto);
  if (env.CF_ACCESS_CLIENT_ID && env.CF_ACCESS_CLIENT_SECRET) {
    out.set("CF-Access-Client-Id", env.CF_ACCESS_CLIENT_ID);
    out.set("CF-Access-Client-Secret", env.CF_ACCESS_CLIENT_SECRET);
  }
  return out;
}

const PASS_RESPONSE_HEADERS = new Set([
  "content-type",
  "content-length",
  "set-cookie",
  "retry-after",
  "www-authenticate",
  "x-request-id",
  "idempotency-key",
  "x-idempotency-key",
  "etag",
  "cache-control",
  "location",
]);

export function buildClientHeaders(upstream: Headers): Headers {
  const out = new Headers();
  upstream.forEach((value, key) => {
    const k = key.toLowerCase();
    if (PASS_RESPONSE_HEADERS.has(k) && !HOP_BY_HOP.has(k)) {
      out.append(key, value);
    }
  });
  return out;
}

function jsonError(status: number, code: string, message: string, rid: string): Response {
  return Response.json({ detail: { code, message } }, {
    status,
    headers: { "x-request-id": rid },
  });
}

async function forward(req: Request, env: Env): Promise<Response> {
  const rid = requestId(req.headers);
  let target: URL;
  try {
    target = upstreamUrl(env, req);
  } catch {
    return jsonError(500, "bad_gateway", "Upstream is not configured", rid);
  }

  const maxBody = parseInt(env.MAX_BODY_BYTES || "1048576", 10);
  const contentLength = parseInt(req.headers.get("content-length") || "0", 10);
  if (contentLength > maxBody) {
    return jsonError(413, "payload_too_large", "Request body too large", rid);
  }

  const headers = buildUpstreamHeaders(req, env, rid);
  const timeoutMs = parseInt(env.FORWARD_TIMEOUT_MS || "30000", 10);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let upstream: Response;
  try {
    upstream = await fetch(target.toString(), {
      method: req.method,
      headers,
      body: ["GET", "HEAD"].includes(req.method) ? undefined : req.body,
      signal: ctrl.signal,
      // @ts-expect-error duplex required for streaming bodies on Workers
      duplex: ["GET", "HEAD"].includes(req.method) ? undefined : "half",
      redirect: "manual",
    });
  } catch (err) {
    clearTimeout(timer);
    const aborted = err instanceof Error && err.name === "AbortError";
    return jsonError(aborted ? 504 : 502, aborted ? "gateway_timeout" : "bad_gateway",
      aborted ? "Upstream timed out" : "Upstream unreachable", rid);
  }
  clearTimeout(timer);

  const clientHeaders = buildClientHeaders(upstream.headers);
  if (!clientHeaders.has("x-request-id")) clientHeaders.set("x-request-id", rid);
  return new Response(upstream.body, { status: upstream.status, headers: clientHeaders });
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    if (req.method === "OPTIONS") {
      // CORS is owned by the FastAPI origin; the worker just passes preflights through.
      return forward(req, env);
    }
    return forward(req, env);
  },
};
