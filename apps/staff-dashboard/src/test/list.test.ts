import { describe, expect, it } from 'vitest';
import { dueLabel, formatDate, formatDateTime } from '../lib/list';

describe('list helpers', () => {
  it('formats dates and handles empties', () => {
    expect(formatDateTime(null)).toBe('—');
    expect(formatDate(undefined)).toBe('—');
    expect(formatDateTime('2026-01-02T03:04:05Z')).toContain('2026');
  });

  it('labels due dates including overdue', () => {
    expect(dueLabel(null).text).toBe('No due date');
    const past = new Date(Date.now() - 3 * 86_400_000).toISOString();
    const overdue = dueLabel(past);
    expect(overdue.overdue).toBe(true);
    expect(overdue.text).toContain('Overdue');
    const future = new Date(Date.now() + 2 * 86_400_000).toISOString();
    expect(dueLabel(future).overdue).toBe(false);
  });
});
