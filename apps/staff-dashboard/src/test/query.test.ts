import { describe, expect, it } from 'vitest';
import { keys } from '../lib/query';

describe('query keys', () => {
  it('scope every key by business id', () => {
    expect(keys.leads('biz-1')).toContain('biz-1');
    expect(keys.lead('biz-1', 'lead-9')).toContain('biz-1');
    expect(keys.tasks('biz-1', { mine: true })).toContain('biz-1');
    expect(keys.overview('biz-1')).toContain('biz-1');
    expect(keys.activity('biz-1', { offset: 0 })).toContain('biz-1');
    // Different businesses never share a key.
    expect(keys.leads('biz-1')).not.toEqual(keys.leads('biz-2'));
  });

  it('never embeds tokens in keys', () => {
    const blob = JSON.stringify([
      keys.me,
      keys.leads('b'),
      keys.tasks('b'),
      keys.notifications('b'),
    ]);
    expect(blob).not.toMatch(/token|secret|bearer/i);
  });
});
