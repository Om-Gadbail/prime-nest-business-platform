/**
 * Render free cold-start readiness: bounded retry, backoff, waking state.
 *
 * Proves the acceptance requirements at the unit level against the shipped
 * implementation (src/lib/readiness.ts + src/lib/api.ts):
 * - temporary failure is detected (network/timeout/502/503/504)
 * - retries use bounded exponential backoff (no infinite loops)
 * - login credentials are preserved across retries (same body re-sent)
 * - terminal errors stay waking-aware (never a bare "Network unavailable")
 * - non-retryable failures (validation/rate-limit) are NOT retried
 * - mutations are never auto-retried (no duplicate payments)
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  COLD_START_EXHAUSTED_MESSAGE,
  coldStartDelay,
  healthUrlFromBase,
  isColdStartStatus,
  waitForBackendReady,
} from '../lib/readiness';
import { ApiError, apiRequest, clearTokens } from '../lib/api';

describe('cold-start status detection', () => {
  it.each([502, 503, 504, 408])('status %i is a wake-up signal', (s) => {
    expect(isColdStartStatus(s)).toBe(true);
  });
  it.each([200, 201, 400, 401, 403, 404, 422, 429])('status %i is not', (s) => {
    expect(isColdStartStatus(s)).toBe(false);
  });
});

describe('bounded exponential backoff', () => {
  it('grows then caps at 10s (+jitter)', () => {
    const d1 = coldStartDelay(1, 1000);
    const d2 = coldStartDelay(2, 1000);
    const d3 = coldStartDelay(3, 1000);
    expect(d1).toBeGreaterThanOrEqual(1000);
    expect(d1).toBeLessThan(1300);
    expect(d2).toBeGreaterThanOrEqual(2000);
    expect(d3).toBeGreaterThanOrEqual(4000);
    for (let attempt = 1; attempt <= 10; attempt += 1) {
      expect(coldStartDelay(attempt, 1000)).toBeLessThanOrEqual(10_250);
    }
  });
});

describe('health URL derivation', () => {
  it('strips /api/v1 from dashboard bases', () => {
    expect(healthUrlFromBase('https://api.example.com/api/v1')).toBe('https://api.example.com/health');
  });
  it('keeps bare website bases', () => {
    expect(healthUrlFromBase('https://api.example.com')).toBe('https://api.example.com/health');
  });
});

describe('waitForBackendReady', () => {
  it('recovers after transient failures (bounded attempts)', async () => {
    let calls = 0;
    const fetchFn = vi.fn(async () => {
      calls += 1;
      if (calls < 3) throw new TypeError('Failed to fetch');
      return new Response('{"status":"ok"}', { status: 200 });
    });
    const res = await waitForBackendReady({ base: 'https://api.example.com', attempts: 6, baseDelayMs: 1, fetchFn: fetchFn as unknown as typeof fetch });
    expect(res.ok).toBe(true);
    expect(res.attempts).toBe(3);
    expect(fetchFn).toHaveBeenCalledTimes(3);
  });
  it('gives up after the budget (never infinite)', async () => {
    const fetchFn = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    const res = await waitForBackendReady({ base: 'https://api.example.com', attempts: 4, baseDelayMs: 1, fetchFn: fetchFn as unknown as typeof fetch });
    expect(res.ok).toBe(false);
    expect(res.attempts).toBe(4);
    expect(fetchFn).toHaveBeenCalledTimes(4);
  });
});

describe('apiRequest cold-start retry', () => {
  const realFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = realFetch;
    clearTokens();
    vi.useRealTimers();
  });

  it('retries a GET through a wake-up then succeeds (no terminal error)', async () => {
    vi.useFakeTimers();
    let calls = 0;
    const stub = vi.fn(async () => {
      calls += 1;
      if (calls === 1) throw new TypeError('Failed to fetch');
      return new Response(JSON.stringify({ hello: 'world' }), { status: 200 });
    });
    globalThis.fetch = stub as unknown as typeof fetch;
    const pending = apiRequest<{ hello: string }>('/api/v1/auth/businesses');
    await vi.runAllTimersAsync();
    await expect(pending).resolves.toEqual({ hello: 'world' });
    expect(stub).toHaveBeenCalledTimes(2);
  });

  it('preserves login credentials across a retry (same body re-sent)', async () => {
    vi.useFakeTimers();
    const bodies: string[] = [];
    const stub = vi.fn(async (_url: unknown, init?: RequestInit) => {
      bodies.push(String(init?.body ?? ''));
      if (bodies.length === 1) throw new TypeError('Failed to fetch');
      return new Response(JSON.stringify({ access_token: 'a', business: null }), { status: 200 });
    });
    globalThis.fetch = stub as unknown as typeof fetch;
    const pending = apiRequest('/api/v1/auth/login', {
      method: 'POST',
      body: { email: 'staff@primefitness.in', password: 'StaffDemo123!' },
      auth: false,
    });
    await vi.runAllTimersAsync();
    await expect(pending).resolves.toEqual({ access_token: 'a', business: null });
    expect(bodies).toHaveLength(2);
    expect(bodies[0]).toContain('StaffDemo123!');
    expect(bodies[0]).toBe(bodies[1]);
  });

  it('ends with a waking-aware error, never bare network text', async () => {
    vi.useFakeTimers();
    const stub = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    globalThis.fetch = stub as unknown as typeof fetch;
    const pending = apiRequest('/api/v1/auth/businesses');
    const assertion = expect(pending).rejects.toMatchObject({ kind: 'unreachable' });
    await vi.runAllTimersAsync();
    await assertion;
    // Bounded: exactly the retry budget, no infinite loop.
    expect(stub.mock.calls.length).toBeLessThanOrEqual(4);
    try {
      await pending;
    } catch (err) {
      expect((err as ApiError).message).toBe(COLD_START_EXHAUSTED_MESSAGE);
    }
  });

  it('never auto-retries a mutating POST (no duplicate payments)', async () => {
    const stub = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    globalThis.fetch = stub as unknown as typeof fetch;
    await expect(apiRequest('/api/v1/payments', { method: 'POST', body: { amount: '10.00' } })).rejects.toMatchObject({
      kind: 'unreachable',
    });
    expect(stub).toHaveBeenCalledTimes(1);
  });

  it('does not retry validation failures', async () => {
    const stub = vi.fn(async () => new Response(JSON.stringify({}), { status: 422 }));
    globalThis.fetch = stub as unknown as typeof fetch;
    await expect(apiRequest('/api/v1/leads/123/status', { method: 'POST', body: {} })).rejects.toMatchObject({
      kind: 'validation',
    });
    expect(stub).toHaveBeenCalledTimes(1);
  });
});
