/**
 * Business configuration for the shared dashboard shell.
 *
 * The SAME codebase serves Prime Fitness and Nest Library: branding,
 * accent, contact info, and feature flags resolve from the business
 * record (backend) with a local preset fallback so the login screen
 * already shows the right identity. Never hardcode domains here —
 * use VITE_* env (see .env.example).
 */

export interface BusinessPreset {
  slug: string;
  name: string;
  shortName: string;
  tagline: string;
  /** Tailwind-friendly accent (hex). */
  accent: string;
  accentSoft: string;
  initials: string;
}

export const BUSINESS_PRESETS: Record<string, BusinessPreset> = {
  prime: {
    slug: 'prime',
    name: 'Prime Fitness',
    shortName: 'Prime',
    tagline: 'Staff operations',
    accent: '#16a34a',
    accentSoft: '#dcfce7',
    initials: 'PF',
  },
  nest: {
    slug: 'nest',
    name: 'Nest Library',
    shortName: 'Nest',
    tagline: 'Staff operations',
    accent: '#7c3aed',
    accentSoft: '#ede9fe',
    initials: 'NL',
  },
  owner: {
    slug: 'owner',
    name: 'Owner Command Center',
    shortName: 'Owner',
    tagline: 'All businesses',
    accent: '#0f172a',
    accentSoft: '#e2e8f0',
    initials: 'OC',
  },
};

export const DEFAULT_PRESET: BusinessPreset = BUSINESS_PRESETS.prime;

function readEnv(key: string): string {
  try {
    const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env;
    return (env?.[key] ?? '').trim();
  } catch {
    return '';
  }
}

export function getConfiguredSlug(): string {
  const raw = readEnv('VITE_BUSINESS_SLUG').toLowerCase();
  if (raw && BUSINESS_PRESETS[raw]) return raw;
  return 'prime';
}

/** Testable slug resolution (env-injectable; same rules as getConfiguredSlug). */
export function getBusinessSlug(env?: Record<string, string | undefined>): string {
  const raw = (env !== undefined ? (env.VITE_BUSINESS_SLUG ?? '') : readEnv('VITE_BUSINESS_SLUG')).trim().toLowerCase();
  if (raw && BUSINESS_PRESETS[raw]) return raw;
  return 'prime';
}

export function getApiBaseUrl(env?: Record<string, string | undefined>): string {
  const raw =
    env !== undefined
      ? (env.VITE_API_BASE_URL ?? '').trim().replace(/\/+$/, '')
      : readEnv('VITE_API_BASE_URL').replace(/\/+$/, '');
  if (!raw) {
    throw new Error(
      'VITE_API_BASE_URL is not set. Copy .env.example to .env and point it at the backend.',
    );
  }
  return raw;
}

export function isBackendConfigured(env?: Record<string, string | undefined>): boolean {
  const raw =
    env !== undefined
      ? (env.VITE_API_BASE_URL ?? '').trim()
      : readEnv('VITE_API_BASE_URL');
  return raw !== '';
}

/** Resolve the preset for a backend business slug (unknown -> default). */
export function presetForSlug(slug: string | null | undefined): BusinessPreset {
  if (slug && BUSINESS_PRESETS[slug]) return BUSINESS_PRESETS[slug];
  return BUSINESS_PRESETS[getConfiguredSlug()] ?? DEFAULT_PRESET;
}

/** Display name: explicit env override wins, else backend name, else preset. */
export function displayName(backendName: string | null | undefined, slug: string): string {
  const override = readEnv('VITE_BUSINESS_NAME');
  if (override) return override;
  if (backendName && backendName.trim()) return backendName.trim();
  return presetForSlug(slug).name;
}
