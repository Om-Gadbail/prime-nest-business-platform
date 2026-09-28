import { describe, expect, it } from 'vitest';
import { getApiBaseUrl, getBusinessSlug, isBackendConfigured, presetForSlug } from '../config/business';

describe('business config', () => {
  it('resolves presets for prime and nest', () => {
    expect(presetForSlug('prime').name).toBe('Prime Fitness');
    expect(presetForSlug('nest').name).toBe('Nest Library');
    expect(presetForSlug('prime').accent).not.toBe(presetForSlug('nest').accent);
  });

  it('falls back for unknown slugs', () => {
    expect(presetForSlug('unknown')).toBeDefined();
    expect(presetForSlug(undefined).slug).toBe('prime');
  });

  it('reads env without hardcoding localhost', () => {
    expect(getApiBaseUrl({ VITE_API_BASE_URL: 'http://localhost:8000/' })).toBe('http://localhost:8000');
    expect(() => getApiBaseUrl({})).toThrow(/VITE_API_BASE_URL/);
    expect(isBackendConfigured({ VITE_API_BASE_URL: '' })).toBe(false);
    expect(isBackendConfigured({ VITE_API_BASE_URL: 'https://api.example.com' })).toBe(true);
  });

  it('resolves the business slug from env', () => {
    expect(getBusinessSlug({ VITE_BUSINESS_SLUG: 'nest' })).toBe('nest');
    expect(getBusinessSlug({ VITE_BUSINESS_SLUG: ' NEST ' })).toBe('nest');
    expect(getBusinessSlug({})).toBe('prime');
  });
});
