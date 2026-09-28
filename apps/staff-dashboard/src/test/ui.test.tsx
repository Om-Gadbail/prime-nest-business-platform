import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ForbiddenState, NoResults } from '../components/ui/states';
import { PriorityBadge, StatusBadge } from '../components/ui/primitives';
import { Pagination } from '../components/ui/forms';

vi.mock('../lib/auth', () => ({
  useSession: () => ({
    me: {
      user: { email: 'viewer@example.com' },
      business: { id: 'biz-1', slug: 'prime', name: 'Prime Fitness' },
      membership: { role: 'VIEWER' },
      permissions: ['dashboard.read', 'leads.read'],
    },
    businesses: [],
    preset: { slug: 'prime', name: 'Prime Fitness', shortName: 'Prime', initials: 'PF', accent: '#16a34a' },
    can: (p: string) => ['dashboard.read', 'leads.read'].includes(p),
    logout: vi.fn(),
    switchBusiness: vi.fn(),
  }),
}));

vi.mock('../features/notifications/hooks', () => ({
  useUnreadCount: () => ({ data: 0 }),
}));

function renderWithProviders(ui: React.ReactElement): ReturnType<typeof render> {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ui primitives', () => {
  it('renders status and priority badges accessibly', () => {
    renderWithProviders(
      <>
        <StatusBadge status="requested" />
        <PriorityBadge priority="urgent" />
      </>,
    );
    expect(screen.getByText('requested')).toBeInTheDocument();
    expect(screen.getByText('urgent')).toBeInTheDocument();
  });

  it('renders forbidden and empty states with helpful copy', () => {
    renderWithProviders(<ForbiddenState />);
    expect(screen.getByText('Not allowed')).toBeInTheDocument();
    renderWithProviders(<NoResults />);
    expect(screen.getByText('No results')).toBeInTheDocument();
  });

  it('paginates with accessible navigation', () => {
    let observed = -1;
    renderWithProviders(
      <Pagination total={45} limit={20} offset={20} onChange={(o) => { observed = o; }} />,
    );
    expect(screen.getByText('Page 2 of 3')).toBeInTheDocument();
    screen.getByRole('button', { name: 'Next' }).click();
    expect(observed).toBe(40);
    screen.getByRole('button', { name: 'Previous' }).click();
    expect(observed).toBe(0);
  });
});
