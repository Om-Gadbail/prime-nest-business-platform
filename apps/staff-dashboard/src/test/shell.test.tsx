import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Shell } from '../components/layout/Shell';

const state = vi.hoisted(() => ({ permissions: [] as string[] }));

vi.mock('../lib/auth', () => ({
  useSession: () => ({
    me: {
      user: { email: 'staff@example.com' },
      business: { id: 'biz-1', slug: 'prime', name: 'Prime Fitness' },
      membership: { role: 'STAFF' },
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

describe('shell navigation', () => {
  it('shows only permitted modules (viewer has no activity link)', () => {
    state.permissions = ['dashboard.read', 'leads.read'];
    renderShell();
    expect(screen.getAllByText('Overview').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Leads').length).toBeGreaterThan(0);
    expect(screen.queryByText('Activity')).toBeNull();
    expect(screen.queryByText('Tasks')).toBeNull();
  });

  it('shows the full operations nav for managers', () => {
    state.permissions = [
      'dashboard.read', 'leads.read', 'bookings.read', 'contacts.read', 'customers.read',
      'tasks.read', 'notifications.read', 'audit.read', 'settings.read',
    ];
    renderShell();
    for (const label of ['Overview', 'Leads', 'Bookings', 'Contacts', 'Customers', 'Tasks', 'Notifications', 'Activity', 'Settings']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it('always shows the active business identity', () => {
    state.permissions = ['dashboard.read'];
    renderShell();
    // Sidebar + header breadcrumb both name the business (never ambiguous).
    expect(screen.getAllByText('Prime Fitness').length).toBeGreaterThanOrEqual(2);
  });
});
