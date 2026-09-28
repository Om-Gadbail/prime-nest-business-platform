/**
 * Visitor attribution capture (UTM / referrer / landing page).
 * Pure browser reads, truncated for transport. The backend stores these
 * on the lead/booking record so staff keep campaign context.
 *
 * Copy to `src/lib/attribution.ts` in the Nest website (identical to the
 * Prime Fitness module — same contract, shared backend).
 */

export interface Attribution {
  landingPage: string;
  referrer: string;
  utmSource: string;
  utmMedium: string;
  utmCampaign: string;
  utmTerm: string;
  utmContent: string;
}

const MAX_URL_CHARS = 500;
const MAX_UTM_CHARS = 200;

function clip(value: string, max: number): string {
  const text = (value ?? '').trim();
  return text.length > max ? text.slice(0, max) : text;
}

function queryParam(search: string, name: string): string {
  try {
    return new URLSearchParams(search).get(name) ?? '';
  } catch {
    return '';
  }
}

/**
 * Capture attribution from the current page. Safe to call during render
 * (returns empty strings outside a browser).
 */
export function captureAttribution(): Attribution {
  if (typeof window === 'undefined' || typeof window.location === 'undefined') {
    return {
      landingPage: '',
      referrer: '',
      utmSource: '',
      utmMedium: '',
      utmCampaign: '',
      utmTerm: '',
      utmContent: '',
    };
  }
  const { location } = window;
  let referrer = '';
  try {
    referrer = window.document?.referrer ?? '';
  } catch {
    referrer = '';
  }
  return {
    landingPage: clip(location.href, MAX_URL_CHARS),
    referrer: clip(referrer, MAX_URL_CHARS),
    utmSource: clip(queryParam(location.search, 'utm_source'), MAX_UTM_CHARS),
    utmMedium: clip(queryParam(location.search, 'utm_medium'), MAX_UTM_CHARS),
    utmCampaign: clip(queryParam(location.search, 'utm_campaign'), MAX_UTM_CHARS),
    utmTerm: clip(queryParam(location.search, 'utm_term'), MAX_UTM_CHARS),
    utmContent: clip(queryParam(location.search, 'utm_content'), MAX_UTM_CHARS),
  };
}
