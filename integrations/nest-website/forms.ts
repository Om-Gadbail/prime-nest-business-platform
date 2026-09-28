/**
 * Nest website form adapters (Block 3 integration package).
 *
 * Maps the Nest website's real form fields to the shared backend client
 * (`backend.ts`). Wire each adapter into the matching form's submit
 * handler — the adapter returns an honest result the UI renders as-is.
 *
 * Copy to `src/lib/nest-leads.ts` in the Nest website (or inline the
 * mappers into existing handlers — the shapes below are the contract).
 */

import {
  isBackendConfigured,
  submitEnquiry,
  submitVisitRequest,
} from './backend';

export type NestInterest =
  | 'Seat Inquiry'
  | 'Book Visit'
  | 'Membership Inquiry'
  | 'Contact'
  | 'Other';

export interface NestFormInput {
  name: string;
  phone: string;
  email?: string;
  interest: NestInterest;
  preferredDate?: string;
  preferredTime?: string;
  message?: string;
  /** Page/form identifier, e.g. 'website:seat-inquiry-form'. */
  source?: string;
  /** Honeypot value — must stay empty for real users. */
  honeypot?: string;
}

export interface NestFormResult {
  ok: boolean;
  message: string;
  /** True when the record reached the backend CRM. */
  viaBackend?: boolean;
  /** Backend request ID for support troubleshooting. */
  backendRequestId?: string;
}

/**
 * Seat / membership / contact enquiry forms -> POST /public/nest/leads.
 */
export async function saveNestEnquiry(input: NestFormInput): Promise<NestFormResult> {
  if (!isBackendConfigured()) {
    return {
      ok: true,
      message:
        'Request saved. Nest Library will confirm on call or WhatsApp — or message directly using the WhatsApp button below.',
      viaBackend: false,
    };
  }
  try {
    const receipt = await submitEnquiry({
      name: input.name,
      phone: input.phone,
      email: input.email,
      message: input.message,
      serviceInterest: input.interest,
      sourceDetail: input.source ?? 'website:seat-inquiry-form',
      preferredTime: input.preferredTime,
      honeypot: input.honeypot,
    });
    return {
      ok: true,
      message: receipt.message,
      viaBackend: true,
      backendRequestId: receipt.requestId,
    };
  } catch (err) {
    return { ok: false, message: messageForFailure(err), viaBackend: false };
  }
}

/**
 * Book-visit form -> POST /public/nest/bookings (creates REQUESTED;
 * staff confirm it — the UI must say "request received", never
 * "booking confirmed").
 */
export async function saveNestVisit(input: NestFormInput): Promise<NestFormResult> {
  if (!isBackendConfigured()) {
    return {
      ok: true,
      message:
        'Request saved. Nest Library will confirm on call or WhatsApp — or message directly using the WhatsApp button below.',
      viaBackend: false,
    };
  }
  try {
    const receipt = await submitVisitRequest({
      name: input.name,
      phone: input.phone,
      email: input.email,
      message: input.message,
      serviceInterest: input.interest,
      sourceDetail: input.source ?? 'website:visit-form',
      preferredDate: input.preferredDate,
      preferredTime: input.preferredTime,
      preferredTimeLabel: input.preferredTime,
      title: input.interest,
      honeypot: input.honeypot,
    });
    return {
      ok: true,
      message: receipt.message,
      viaBackend: true,
      backendRequestId: receipt.requestId,
    };
  } catch (err) {
    return { ok: false, message: messageForFailure(err), viaBackend: false };
  }
}

function messageForFailure(err: unknown): string {
  if (err instanceof Error && err.name === 'BackendError') {
    return err.message;
  }
  return 'Could not reach our server. Please try again or contact Nest Library on call or WhatsApp.';
}

/** Backend contract — resolved through the centralized client. */
export const NEST_API_CONTRACT = {
  method: 'POST',
  path: '/api/v1/public/nest/leads',
  bookingsPath: '/api/v1/public/nest/bookings',
  configPath: '/api/v1/public/nest/config',
  contentType: 'application/json',
} as const;
