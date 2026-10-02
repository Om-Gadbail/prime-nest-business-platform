/**
 * Centralized typed backend API client.
 *
 * The ONLY module that talks to the FastAPI platform — components use
 * the query/mutation hooks in `features/*`, never fetch() directly.
 *
 * Auth model (mirrors backend/auth.py):
 * - Access token: short-lived Bearer, kept in memory only (never
 *   localStorage). Sent as `Authorization: Bearer …`.
 * - Refresh token: opaque; prefer the Secure HttpOnly cookie set by the
 *   backend, with the JSON copy as fallback for non-cookie contexts.
 * On 401 the client attempts one refresh, then surfaces
 * `ApiError(kind='unauthorized')` so the session provider logs out
 * gracefully (no infinite loading states).
 */

import { getApiBaseUrl } from '../config/business';
import {
  COLD_START_EXHAUSTED_MESSAGE,
  coldStartDelay,
  isColdStartStatus,
} from './readiness';

export type ApiErrorKind =
  | 'unauthorized'
  | 'forbidden'
  | 'not_found'
  | 'validation'
  | 'conflict'
  | 'rate_limited'
  | 'server'
  | 'timeout'
  | 'unreachable';

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  readonly requestId?: string;

  constructor(kind: ApiErrorKind, message: string, extra?: { status?: number; requestId?: string }) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = extra?.status;
    this.requestId = extra?.requestId;
  }
}

const TIMEOUT_MS = 15000;

/**
 * Bounded cold-start retries for idempotent traffic only.
 * GET requests plus the auth login/refresh exchange may be retried on
 * network failure/timeout/502/503/504 (Render free wake-up). Mutating
 * POST/PATCH/PUT/DELETE are never auto-retried (no duplicate
 * payments/leads/bookings/memberships); they fail with a waking-aware
 * message so the UI can offer a manual retry with input preserved.
 */
const COLD_START_RETRY_ATTEMPTS = 4;

function isRetryableRequest(method: string, path: string): boolean {
  if (method === 'GET') return true;
  return path.startsWith('/api/v1/auth/login') || path.startsWith('/api/v1/auth/refresh');
}

let accessToken: string | null = null;
let refreshToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setTokens(next: { access?: string | null; refresh?: string | null }): void {
  if ('access' in next) accessToken = next.access ?? null;
  if ('refresh' in next) refreshToken = next.refresh ?? null;
}

export function clearTokens(): void {
  accessToken = null;
  refreshToken = null;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function subscribeUnauthorized(fn: () => void): void {
  onUnauthorized = fn;
}

function friendlyMessage(status: number, body: Record<string, unknown>, fallback: string): string {
  try {
    const err = body.error as { message?: unknown } | undefined;
    if (err && typeof err.message === 'string' && err.message.trim()) return err.message;
    if (typeof body.message === 'string' && body.message.trim()) return body.message;
  } catch {
    // fall through
  }
  if (status === 403) return 'You do not have permission to do that.';
  if (status === 404) return 'Not found.';
  return fallback;
}

async function parseJsonSafe(res: Response): Promise<Record<string, unknown>> {
  try {
    const data: unknown = await res.json();
    if (data && typeof data === 'object' && !Array.isArray(data)) return data as Record<string, unknown>;
    return {};
  } catch {
    return {};
  }
}

function toApiError(status: number, body: Record<string, unknown>, requestId?: string): ApiError {
  if (status === 401) return new ApiError('unauthorized', 'Your session expired. Please sign in again.', { status, requestId });
  if (status === 403) return new ApiError('forbidden', friendlyMessage(status, body, 'Forbidden.'), { status, requestId });
  if (status === 404) return new ApiError('not_found', friendlyMessage(status, body, 'Not found.'), { status, requestId });
  if (status === 422 || status === 400) return new ApiError('validation', friendlyMessage(status, body, 'Please check the input.'), { status, requestId });
  if (status === 409) return new ApiError('conflict', friendlyMessage(status, body, 'Conflicts with existing data.'), { status, requestId });
  if (status === 429) return new ApiError('rate_limited', friendlyMessage(status, body, 'Too many requests. Try again shortly.'), { status, requestId });
  // Render free cold start surfaces as 502/503/504: report as unreachable
  // (waking) rather than a generic server error so the UI can show the
  // waking-up state instead of a terminal failure.
  if (isColdStartStatus(status)) {
    return new ApiError('unreachable', COLD_START_EXHAUSTED_MESSAGE, { status, requestId });
  }
  return new ApiError('server', friendlyMessage(status, body, 'Something went wrong. Try again.'), { status, requestId });
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Set false for login/refresh (no token yet / rotation). */
  auth?: boolean;
  timeoutMs?: number;
}

export async function apiRequest<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const base = getApiBaseUrl();
  const url = new URL(`${base}${path}`);
  if (opts.query) {
    for (const [key, value] of Object.entries(opts.query)) {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
    }
  }
  const useAuth = opts.auth !== false;
  const method = opts.method ?? 'GET';
  const retryable = isRetryableRequest(method, path);

  async function sendOnce(token: string | null, timeoutMs: number): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const headers: Record<string, string> = { Accept: 'application/json' };
      if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
      if (token) headers.Authorization = `Bearer ${token}`;
      return await fetch(url.toString(), {
        method,
        headers,
        credentials: 'include',
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
        signal: controller.signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw new ApiError('timeout', COLD_START_EXHAUSTED_MESSAGE);
      }
      throw new ApiError('unreachable', COLD_START_EXHAUSTED_MESSAGE);
    } finally {
      clearTimeout(timer);
    }
  }

  let lastColdStartError: ApiError | null = null;
  const maxAttempts = retryable ? COLD_START_RETRY_ATTEMPTS : 1;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    let res: Response;
    try {
      res = await sendOnce(useAuth ? accessToken : null, opts.timeoutMs ?? TIMEOUT_MS);
    } catch (err) {
      // Network failure / timeout on a retryable request: back off and retry.
      if (retryable && err instanceof ApiError && (err.kind === 'unreachable' || err.kind === 'timeout') && attempt < maxAttempts) {
        lastColdStartError = err;
        await new Promise((r) => setTimeout(r, coldStartDelay(attempt)));
        continue;
      }
      throw err;
    }
    // Edge cold-start status on a retryable request: back off and retry.
    if (retryable && isColdStartStatus(res.status) && attempt < maxAttempts) {
      // Drain the body so the connection can be reused, then wait.
      try {
        await res.arrayBuffer();
      } catch {
        // ignore drain errors
      }
      lastColdStartError = new ApiError('unreachable', COLD_START_EXHAUSTED_MESSAGE, {
        status: res.status,
        requestId: res.headers.get('X-Request-ID') ?? undefined,
      });
      await new Promise((r) => setTimeout(r, coldStartDelay(attempt)));
      continue;
    }
    // One transparent refresh on 401 (auth endpoints excluded to avoid loops).
    if (res.status === 401 && useAuth && !path.startsWith('/api/v1/auth/')) {
      const refreshed = await tryRefresh();
      if (refreshed) {
        res = await sendOnce(accessToken, opts.timeoutMs ?? TIMEOUT_MS);
      } else {
        const body = await parseJsonSafe(res);
        onUnauthorized?.();
        throw toApiError(401, body, res.headers.get('X-Request-ID') ?? undefined);
      }
    }
    const requestId = res.headers.get('X-Request-ID') ?? undefined;
    if (res.status === 204) return undefined as T;
    const body = await parseJsonSafe(res);
    if (res.ok) return body as T;
    throw toApiError(res.status, body, requestId);
  }
  throw lastColdStartError ?? new ApiError('unreachable', COLD_START_EXHAUSTED_MESSAGE);
}

async function tryRefresh(): Promise<boolean> {
  try {
    const base = getApiBaseUrl();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const res = await fetch(`${base}/api/v1/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ refresh_token: refreshToken }),
        signal: controller.signal,
      });
      const body = await parseJsonSafe(res);
      if (!res.ok) return false;
      const next = body as { access_token?: string; refresh_token?: string };
      if (typeof next.access_token === 'string') {
        setTokens({ access: next.access_token, refresh: next.refresh_token ?? refreshToken });
        return true;
      }
      return false;
    } finally {
      clearTimeout(timer);
    }
  } catch {
    return false;
  }
}

export const api = {
  get: <T>(path: string, query?: RequestOptions['query']) => apiRequest<T>(path, { query }),
  post: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: 'POST', body }),
  patch: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: 'PATCH', body }),
  put: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: 'PUT', body }),
  del: <T>(path: string) => apiRequest<T>(path, { method: 'DELETE' }),
  /** Auth endpoints skip the Bearer header (nothing to send yet). */
  authPost: <T>(path: string, body?: unknown) =>
    apiRequest<T>(path, { method: 'POST', body, auth: false }),
};
