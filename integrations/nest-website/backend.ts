/**
 * Nest Library backend API client (Block 3 integration package).
 *
 * DROP-IN module for the Nest website (Vite + React). Mirrors the proven
 * Prime Fitness integration (`prime-fitness-website/src/lib/backend.ts`)
 * against the SAME shared FastAPI platform — only the business slug and
 * the form vocabulary differ.
 *
 * ALL backend traffic goes through this module — no scattered fetch()
 * calls in components. Talks to the shared FastAPI platform:
 *
 *   GET  /api/v1/public/nest/config
 *   POST /api/v1/public/nest/leads      (Idempotency-Key)
 *   POST /api/v1/public/nest/bookings   (Idempotency-Key)
 *
 * Honesty rules enforced here:
 * - A booking POST creates a REQUEST, never a confirmation.
 * - No secrets: only VITE_API_BASE_URL / VITE_BUSINESS_SLUG are read.
 * - Backend failures are typed (BackendError.kind) so forms render
 *   validation / rate-limit / timeout / server-error states distinctly.
 *
 * USAGE:
 *   1. Copy this file to `src/lib/backend.ts` in the Nest website.
 *   2. Copy `attribution.ts` to `src/lib/attribution.ts`.
 *   3. Copy `forms.ts` to `src/lib/nest-leads.ts` (or wire its mappers
 *      into the existing form handlers).
 *   4. Set VITE_API_BASE_URL + VITE_BUSINESS_SLUG=nest (see .env.example).
 */

import { captureAttribution } from './attribution';

export const BUSINESS_SLUG = 'nest';

const DEFAULT_TIMEOUT_MS = 12000;

export type BackendErrorKind =
  | 'validation'
  | 'rate_limited'
  | 'disabled'
  | 'server'
  | 'timeout'
  | 'unreachable';

export class BackendError extends Error {
  readonly kind: BackendErrorKind;
  readonly status?: number;
  readonly requestId?: string;
  readonly retryAfterSeconds?: number;

  constructor(kind: BackendErrorKind, message: string, extra?: { status?: number; requestId?: string; retryAfterSeconds?: number }) {
    super(message);
    this.name = 'BackendError';
    this.kind = kind;
    this.status = extra?.status;
    this.requestId = extra?.requestId;
    this.retryAfterSeconds = extra?.retryAfterSeconds;
  }
}

export interface PublicConfig {
  slug: string;
  name: string;
  businessType: string;
  timezone: string;
  leadCaptureEnabled: boolean;
  bookingEnabled: boolean;
}

/** Seat / membership / contact enquiry submitted from the Nest website. */
export interface NestEnquiry {
  name: string;
  phone: string;
  email?: string;
  message?: string;
  /** e.g. 'Seat Inquiry' | 'Membership Inquiry' | 'Contact' | 'Other'. */
  serviceInterest?: string;
  sourceDetail?: string;
  preferredTime?: string;
  /** Honeypot — must stay empty for real users. */
  honeypot?: string;
}

/** Visit-booking request submitted from the Nest website. */
export interface NestVisitRequest extends NestEnquiry {
  /** 'YYYY-MM-DD' from the date input; sent as local-midnight ISO. */
  preferredDate?: string;
  preferredTimeLabel?: string;
  title?: string;
}

export interface EnquiryReceipt {
  leadId: string;
  message: string;
  requestId?: string;
}

export interface VisitReceipt {
  bookingId: string;
  message: string;
  requestId?: string;
}

type EnvRecord = Record<string, string | undefined> | undefined;

function readEnv(): EnvRecord {
  try {
    // NOTE: access import.meta.env DIRECTLY (never via an alias variable).
    // Vite statically replaces the `import.meta.env` member expression at
    // build/dev-transform time; reading it through `const meta = import.meta`
    // defeats that replacement and the browser always sees an empty env.
    return (import.meta.env ?? undefined) as EnvRecord;
  } catch {
    return undefined;
  }
}

/** Base URL of the FastAPI backend. Undefined when not configured. */
export function getApiBaseUrl(env: EnvRecord = readEnv()): string | undefined {
  const raw = (env?.VITE_API_BASE_URL ?? '').trim().replace(/\/+$/, '');
  return raw || undefined;
}

export function getBusinessSlug(env: EnvRecord = readEnv()): string {
  return (env?.VITE_BUSINESS_SLUG ?? '').trim().toLowerCase() || BUSINESS_SLUG;
}

export function isBackendConfigured(env?: EnvRecord): boolean {
  return getApiBaseUrl(env) !== undefined;
}

function makeIdempotencyKey(): string {
  try {
    if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
      return crypto.randomUUID();
    }
  } catch {
    // fall through
  }
  return `web-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
}

async function parseJsonSafe(res: Response): Promise<Record<string, unknown>> {
  try {
    const data: unknown = await res.json();
    if (data && typeof data === 'object' && !Array.isArray(data)) {
      return data as Record<string, unknown>;
    }
    return {};
  } catch {
    return {};
  }
}

function envelopeMessage(data: Record<string, unknown>, fallback: string): string {
  try {
    const err = data.error as { message?: unknown } | undefined;
    if (err && typeof err.message === 'string' && err.message.trim()) {
      return err.message;
    }
    if (typeof data.message === 'string' && data.message.trim()) {
      return data.message;
    }
  } catch {
    // ignore shaping errors, use fallback
  }
  return fallback;
}

async function postPublic<T>(
  path: 'leads' | 'bookings',
  body: Record<string, unknown>,
  opts?: { timeoutMs?: number; idempotencyKey?: string },
): Promise<{ data: T; requestId?: string }> {
  const base = getApiBaseUrl();
  if (!base) {
    throw new BackendError('unreachable', 'Backend is not configured.');
  }
  const slug = getBusinessSlug();
  const controller = new AbortController();
  const timeoutMs = opts?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(`${base}/api/v1/public/${slug}/${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': opts?.idempotencyKey ?? makeIdempotencyKey(),
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timer);
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new BackendError('timeout', 'The request timed out. Please try again.');
    }
    throw new BackendError(
      'unreachable',
      'Could not reach our server. Please try again or contact Nest Library on call or WhatsApp.',
    );
  } finally {
    clearTimeout(timer);
  }

  const requestId = res.headers.get('X-Request-ID') ?? undefined;
  const data = await parseJsonSafe(res);
  if (res.status === 201 || res.status === 200) {
    return { data: data as T, requestId };
  }
  if (res.status === 422 || res.status === 400) {
    throw new BackendError('validation', envelopeMessage(data, 'Please check the form and try again.'), {
      status: res.status,
      requestId,
    });
  }
  if (res.status === 429) {
    const retryAfter = Number(res.headers.get('Retry-After') ?? '0');
    throw new BackendError(
      'rate_limited',
      'Too many requests right now. Please wait a little and try again.',
      { status: 429, requestId, retryAfterSeconds: Number.isFinite(retryAfter) ? retryAfter : undefined },
    );
  }
  if (res.status === 403) {
    throw new BackendError(
      'disabled',
      'Online enquiries are currently paused. Please call or WhatsApp us instead.',
      { status: 403, requestId },
    );
  }
  if (res.status === 413) {
    throw new BackendError('validation', 'Your message is too long. Please shorten it and try again.', {
      status: 413,
      requestId,
    });
  }
  throw new BackendError(
    'server',
    'Something went wrong on our side. Please try again or contact Nest Library on call or WhatsApp.',
    { status: res.status, requestId },
  );
}

/** Map the Nest website interest vocabulary to backend booking types. */
export function mapInterestToBookingType(interest: string): string {
  switch (interest) {
    case 'Book Visit':
    case 'Seat Inquiry':
      return 'visit';
    case 'Membership Inquiry':
      return 'trial';
    case 'Contact':
    case 'Other':
    default:
      return 'enquiry';
  }
}

export async function submitEnquiry(input: NestEnquiry): Promise<EnquiryReceipt> {
  const attr = captureAttribution();
  const { data, requestId } = await postPublic<{ lead_id?: string; message?: string }>('leads', {
    name: input.name,
    phone: input.phone,
    email: input.email || null,
    message: input.message ?? '',
    service_interest: input.serviceInterest ?? '',
    source_detail: input.sourceDetail ?? 'website:seat-inquiry-form',
    preferred_time: input.preferredTime ?? '',
    consent_marketing: false,
    landing_page: attr.landingPage,
    referrer: attr.referrer,
    utm_source: attr.utmSource,
    utm_medium: attr.utmMedium,
    utm_campaign: attr.utmCampaign,
    utm_term: attr.utmTerm,
    utm_content: attr.utmContent,
    website_url: input.honeypot ?? '',
  });
  return {
    leadId: typeof data.lead_id === 'string' ? data.lead_id : '',
    message:
      typeof data.message === 'string' && data.message
        ? data.message
        : 'Enquiry received — Nest Library will confirm with you shortly.',
    requestId,
  };
}

export async function submitVisitRequest(input: NestVisitRequest): Promise<VisitReceipt> {
  const attr = captureAttribution();
  const { data, requestId } = await postPublic<{ booking_id?: string; message?: string }>(
    'bookings',
    {
      name: input.name,
      phone: input.phone,
      email: input.email || null,
      booking_type: mapInterestToBookingType(input.serviceInterest ?? ''),
      title: input.title ?? input.serviceInterest ?? 'Visit request',
      requested_start_at: input.preferredDate ? `${input.preferredDate}T00:00:00` : null,
      preferred_time_label: input.preferredTimeLabel ?? input.preferredTime ?? '',
      message: input.message ?? '',
      source_detail: input.sourceDetail ?? 'website:visit-form',
      landing_page: attr.landingPage,
      referrer: attr.referrer,
      utm_source: attr.utmSource,
      utm_medium: attr.utmMedium,
      utm_campaign: attr.utmCampaign,
      website_url: input.honeypot ?? '',
    },
  );
  return {
    bookingId: typeof data.booking_id === 'string' ? data.booking_id : '',
    // Honest language: the backend creates a REQUEST; staff confirm it.
    message:
      typeof data.message === 'string' && data.message
        ? data.message
        : 'Request received — Nest Library will confirm with you shortly.',
    requestId,
  };
}

export async function getPublicConfig(timeoutMs = DEFAULT_TIMEOUT_MS): Promise<PublicConfig> {
  const base = getApiBaseUrl();
  if (!base) {
    throw new BackendError('unreachable', 'Backend is not configured.');
  }
  const slug = getBusinessSlug();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${base}/api/v1/public/${slug}/config`, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });
    const data = await parseJsonSafe(res);
    if (!res.ok) {
      throw new BackendError('server', 'Could not load business configuration.', {
        status: res.status,
      });
    }
    return {
      slug: String(data.slug ?? slug),
      name: String(data.name ?? 'Nest Library'),
      businessType: String(data.business_type ?? ''),
      timezone: String(data.timezone ?? 'UTC'),
      leadCaptureEnabled: data.lead_capture_enabled === true,
      bookingEnabled: data.booking_enabled === true,
    };
  } catch (err) {
    if (err instanceof BackendError) throw err;
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new BackendError('timeout', 'The request timed out. Please try again.');
    }
    throw new BackendError('unreachable', 'Could not reach our server.');
  } finally {
    clearTimeout(timer);
  }
}
