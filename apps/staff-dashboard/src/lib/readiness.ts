/**
 * Backend readiness / Render free cold-start handling.
 *
 * Render Free sleeps after inactivity. The first request while the backend
 * is waking manifests as a network failure (fetch throws), a timeout, or an
 * edge 502/503/504 — NOT an auth failure. The UI must not show a terminal
 * "Network unavailable" immediately; it must wait, retry with bounded
 * exponential backoff, preserve user input, and continue normally once the
 * backend answers.
 *
 * Safety rules (never weakened):
 * - Bounded retries only (no infinite loops, no request storms).
 * - Automatic retry is limited to idempotent reads (GET) plus the
 *   auth login/refresh exchange. Mutating POST/PATCH/PUT/DELETE are never
 *   auto-retried here (payments/leads/bookings/memberships must not
 *   duplicate). Callers surface a manual "waking up, try again" state.
 * - No auth bypass, no CORS bypass, no secrets in this module.
 */

export const WAKING_MESSAGE =
  'Backend is waking up. Retrying automatically — your entries are kept.';

export const COLD_START_EXHAUSTED_MESSAGE =
  'Backend is still waking up. Wait a moment and try again — your entries were kept.';

const DEFAULT_MAX_ATTEMPTS = 6;
const DEFAULT_BASE_DELAY_MS = 1000;
const DEFAULT_MAX_DELAY_MS = 10_000;
const DEFAULT_PROBE_TIMEOUT_MS = 10_000;

/** Statuses that mean "backend/edge temporarily unavailable", worth a retry. */
export function isColdStartStatus(status: number | undefined): boolean {
  return status === 502 || status === 503 || status === 504 || status === 408;
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Bounded exponential backoff with a small jitter (prevents thundering herds). */
export function coldStartDelay(attempt: number, baseMs = DEFAULT_BASE_DELAY_MS): number {
  const exp = baseMs * 2 ** Math.max(0, attempt - 1);
  const capped = Math.min(exp, DEFAULT_MAX_DELAY_MS);
  return capped + Math.floor(Math.random() * 250);
}

/** Derive the liveness URL from any API base (bare host or host + /api/v1). */
export function healthUrlFromBase(base: string): string {
  const stripped = base.replace(/\/+$/, '').replace(/\/api\/v1\/?$/, '');
  return `${stripped}/health`;
}

export interface WaitForReadyOptions {
  base?: string | null;
  attempts?: number;
  baseDelayMs?: number;
  timeoutMs?: number;
  fetchFn?: typeof fetch;
}

export interface WaitForReadyResult {
  ok: boolean;
  attempts: number;
  lastStatus?: number;
}

/**
 * Poll GET /health until 200 or the attempt budget is spent.
 * Resolves (never rejects): callers branch on `ok`.
 */
export async function waitForBackendReady(
  opts: WaitForReadyOptions = {},
): Promise<WaitForReadyResult> {
  const maxAttempts = opts.attempts ?? DEFAULT_MAX_ATTEMPTS;
  const baseDelayMs = opts.baseDelayMs ?? DEFAULT_BASE_DELAY_MS;
  const timeoutMs = opts.timeoutMs ?? DEFAULT_PROBE_TIMEOUT_MS;
  const doFetch = opts.fetchFn ?? fetch;
  let lastStatus: number | undefined;
  let url: string | null = null;
  if (opts.base) {
    try {
      url = healthUrlFromBase(opts.base);
    } catch {
      url = null;
    }
  }
  if (!url) {
    try {
      const { getApiBaseUrl } = await import('../config/business');
      url = healthUrlFromBase(getApiBaseUrl());
    } catch {
      return { ok: false, attempts: 0 };
    }
  }
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await doFetch(url, {
        method: 'GET',
        credentials: 'omit',
        signal: controller.signal,
      });
      lastStatus = res.status;
      if (res.status === 200) return { ok: true, attempts: attempt, lastStatus };
      // Non-200 (including 503 not-ready): back off and retry while budget lasts.
    } catch {
      lastStatus = undefined;
    } finally {
      clearTimeout(timer);
    }
    if (attempt < maxAttempts) await sleep(coldStartDelay(attempt, baseDelayMs));
  }
  return { ok: false, attempts: maxAttempts, lastStatus };
}

/** True when an ApiError-shaped failure looks like a cold start (retryable). */
export function isColdStartError(err: unknown): boolean {
  if (!err || typeof err !== 'object') return false;
  const rec = err as { kind?: unknown; status?: unknown; code?: unknown; message?: unknown };
  if (typeof rec.status === 'number' && isColdStartStatus(rec.status)) return true;
  if (rec.kind === 'unreachable' || rec.kind === 'timeout') return true;
  // Raw fetch TypeErrors ("Failed to fetch", "NetworkError", "Load failed").
  if (typeof rec.message === 'string' && /failed to fetch|networkerror|load failed|network request failed/i.test(rec.message)) {
    return true;
  }
  return false;
}
