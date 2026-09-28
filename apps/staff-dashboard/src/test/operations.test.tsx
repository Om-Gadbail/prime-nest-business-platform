import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Shell } from '../components/layout/Shell';
import { getBusinessSlug, presetForSlug } from '../config/business';
import { keys } from '../lib/query';
import { formatMoney, formatRate, isOverdueDate } from '../lib/list';

const state = vi.hoisted(() => ({ permissions: [] as string[] }));

vi.mock('../lib/auth', () => ({
  useSession: () => ({
    me: {
      user: { email: 'owner@example.com' },
      business: { id: 'biz-1', slug: 'prime', name: 'Prime Fitness' },
      membership: { role: 'OWNER' },
      permissions: state.permissions,
    },
    businesses: [],
    preset: { slug: 'prime', name: 'Prime Fitness', shortName: 'Prime', initials: 'PF', accent: '#16a34a' },
    can: (p: string) => state.permissions.includes(p),
    logout: vi.fn(),
    switchBusiness: vi.fn(),
  }),
}));

vi.mock('../features/notifications/hooks', () => ({
  useUnreadCount: () => ({ data: 0 }),
}));

function renderShell(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<div>home</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('blocks 5-7 operations', () => {
  it('shows owner + operational nav for owners, hides them from viewers', () => {
    state.permissions = [
      'dashboard.read', 'owner.dashboard.read', 'owner.combined.read',
      'members.read', 'memberships.read', 'membership_plans.read', 'payments.read',
      'attendance.read', 'renewals.read', 'seats.read', 'approvals.read',
    ];
    const { unmount } = render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={['/']}>
          <Routes>
            <Route element={<Shell />}>
              <Route index element={<div>home</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    for (const label of ['Owner', 'Members', 'Memberships', 'Plans', 'Payments', 'Attendance', 'Renewals', 'Seats', 'Approvals']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    unmount();
  });

  it('hides operational modules without permission', () => {
    state.permissions = ['dashboard.read', 'leads.read'];
    renderShell();
    expect(screen.queryByText('Owner')).toBeNull();
    expect(screen.queryByText('Members')).toBeNull();
    expect(screen.queryByText('Seats')).toBeNull();
    expect(screen.queryByText('Approvals')).toBeNull();
  });

  it('formats money without float math and rates as percent', () => {
    expect(formatMoney('1500.00', 'INR')).toContain('1,500.00');
    expect(formatMoney('1499.90', 'INR')).toContain('1,499.90');
    expect(formatMoney(null)).toBe('—');
    expect(formatRate(2 / 3)).toBe('66.7%');
    expect(formatRate(0)).toBe('0.0%');
    expect(formatRate(null)).toBe('—');
  });

  it('flags overdue renewal dates', () => {
    expect(isOverdueDate('2000-01-01')).toBe(true);
    expect(isOverdueDate('2999-01-01')).toBe(false);
    expect(isOverdueDate(null)).toBe(false);
  });

  it('resolves business slugs and presets per business', () => {
    expect(getBusinessSlug({ VITE_BUSINESS_SLUG: 'nest' })).toBe('nest');
    expect(getBusinessSlug({ VITE_BUSINESS_SLUG: 'unknown' })).toBe('prime');
    expect(presetForSlug('nest').shortName).toBe('Nest');
    expect(presetForSlug('prime').shortName).toBe('Prime');
  });

  it('scopes every operational query key by business id', () => {
    expect(keys.members('biz-1')[1]).toBe('biz-1');
    expect(keys.memberships('biz-1')[1]).toBe('biz-1');
    expect(keys.payments('biz-1')[1]).toBe('biz-1');
    expect(keys.attendance('biz-1')[1]).toBe('biz-1');
    expect(keys.seats('biz-1')[1]).toBe('biz-1');
    expect(keys.ownerCombined('biz-1')[1]).toBe('biz-1');
  });
});
