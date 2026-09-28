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
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), opts.timeoutMs ?? TIMEOUT_MS);

  async function send(token: string | null): Promise<Response> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
    if (token) headers.Authorization = `Bearer ${token}`;
    let res: Response;
    try {
      res = await fetch(url.toString(), {
        method: opts.method ?? 'GET',
        headers,
        credentials: 'include',
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
        signal: controller.signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw new ApiError('timeout', 'The request timed out. Please try again.');
      }
      throw new ApiError('unreachable', 'Could not reach the server. Check your connection.');
    }
    return res;
  }

  try {
    let res = await send(useAuth ? accessToken : null);
    // One transparent refresh on 401 (auth endpoints excluded to avoid loops).
    if (res.status === 401 && useAuth && !path.startsWith('/api/v1/auth/')) {
      const refreshed = await tryRefresh();
      if (refreshed) {
        res = await send(accessToken);
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
  } finally {
    clearTimeout(timer);
  }
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
