import { useState } from 'react';

/** Shared server-driven list state (pagination + debounced search handled by callers). */
export function useListParams(initialLimit = 20): {
  limit: number;
  offset: number;
  search: string;
  setOffset: (offset: number) => void;
  setSearch: (search: string) => void;
} {
  const [offset, setOffset] = useState(0);
  const [search, setSearchState] = useState('');
  const setSearch = (value: string): void => {
    setSearchState(value);
    setOffset(0);
  };
  return { limit: initialLimit, offset, search, setOffset, setSearch };
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return String(value);
  }
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleDateString();
  } catch {
    return String(value);
  }
}

/** Overdue check for pipeline dates (renewals, follow-ups). */
export function isOverdueDate(value: string | null | undefined): boolean {
  return dueLabel(value).overdue;
}

/** Relative due label for tasks/follow-ups (overdue highlighting). */
export function dueLabel(value: string | null | undefined): { text: string; overdue: boolean } {
  if (!value) return { text: 'No due date', overdue: false };
  const due = new Date(value).getTime();
  if (Number.isNaN(due)) return { text: String(value), overdue: false };
  const overdue = due < Date.now();
  const days = Math.round((due - Date.now()) / 86_400_000);
  if (overdue) return { text: days === 0 ? 'Due today' : `Overdue by ${Math.abs(days)}d`, overdue: true };
  if (days === 0) return { text: 'Due today', overdue: false };
  if (days === 1) return { text: 'Due tomorrow', overdue: false };
  return { text: `Due in ${days}d`, overdue: false };
}

/**
 * Display-only money formatting. The backend is authoritative for all
 * math (Decimal); this only renders the string amounts it returns.
 * Falls back to a plain code-prefixed string when Intl fails.
 */
export function formatMoney(amount: string | number | null | undefined, currency = 'INR'): string {
  if (amount === null || amount === undefined || amount === '') return '—';
  const numeric = typeof amount === 'number' ? amount : Number(amount);
  if (!Number.isFinite(numeric)) return `${currency} ${String(amount)}`;
  try {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
    }).format(numeric);
  } catch {
    return `${currency} ${numeric.toFixed(2)}`;
  }
}

/** Rate in [0,1] as a one-decimal percent string (0 -> "0%"). */
export function formatRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return '—';
  return `${(rate * 100).toFixed(1)}%`;
}
