import { QueryClient } from '@tanstack/react-query';

/**
 * Shared TanStack Query client — the ONLY server-state cache.
 * No second cache system anywhere in the app.
 *
 * - Query keys always include the business id + resource identity.
 * - Tokens/secrets never go into query keys.
 * - Mutations invalidate the affected scopes (see feature hooks).
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        retry: (count, err) => {
          const status = (err as { status?: number })?.status;
          if (status === 401 || status === 403 || status === 404) return false;
          return count < 1;
        },
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

/** Business-scoped key helpers (business id first, always). */
export const keys = {
  me: ['me'],
  businesses: ['businesses'],
  business: (businessId: string) => ['business', businessId],
  settings: (businessId: string) => ['settings', businessId],
  overview: (businessId: string) => ['dashboard', businessId, 'overview'],
  leadsSummary: (businessId: string) => ['dashboard', businessId, 'leads-summary'],
  bookingsSummary: (businessId: string) => ['dashboard', businessId, 'bookings-summary'],
  activity: (businessId: string, params?: unknown) => ['dashboard', businessId, 'activity', params ?? 'all'],
  leads: (businessId: string, params?: unknown) => ['leads', businessId, params ?? 'all'],
  lead: (businessId: string, id: string) => ['leads', businessId, 'detail', id],
  leadActivities: (businessId: string, id: string) => ['leads', businessId, 'activities', id],
  bookings: (businessId: string, params?: unknown) => ['bookings', businessId, params ?? 'all'],
  booking: (businessId: string, id: string) => ['bookings', businessId, 'detail', id],
  contacts: (businessId: string, params?: unknown) => ['contacts', businessId, params ?? 'all'],
  contact: (businessId: string, id: string) => ['contacts', businessId, 'detail', id],
  customers: (businessId: string, params?: unknown) => ['customers', businessId, params ?? 'all'],
  customer: (businessId: string, id: string) => ['customers', businessId, 'detail', id],
  tasks: (businessId: string, params?: unknown) => ['tasks', businessId, params ?? 'all'],
  task: (businessId: string, id: string) => ['tasks', businessId, 'detail', id],
  notifications: (businessId: string, params?: unknown) => ['notifications', businessId, params ?? 'all'],
  unreadCount: (businessId: string) => ['notifications', businessId, 'unread-count'],
  // Blocks 5-7 operational modules (business id first, always).
  members: (businessId: string, params?: unknown) => ['members', businessId, params ?? 'all'],
  member: (businessId: string, id: string) => ['members', businessId, 'detail', id],
  memberProfile: (businessId: string, id: string) => ['members', businessId, 'profile', id],
  plans: (businessId: string, params?: unknown) => ['plans', businessId, params ?? 'all'],
  plan: (businessId: string, id: string) => ['plans', businessId, 'detail', id],
  memberships: (businessId: string, params?: unknown) => ['memberships', businessId, params ?? 'all'],
  membership: (businessId: string, id: string) => ['memberships', businessId, 'detail', id],
  renewals: (businessId: string, params?: unknown) => ['renewals', businessId, params ?? 'all'],
  payments: (businessId: string, params?: unknown) => ['payments', businessId, params ?? 'all'],
  payment: (businessId: string, id: string) => ['payments', businessId, 'detail', id],
  attendance: (businessId: string, params?: unknown) => ['attendance', businessId, params ?? 'all'],
  seats: (businessId: string, params?: unknown) => ['seats', businessId, params ?? 'all'],
  seatAreas: (businessId: string) => ['seats', businessId, 'areas'],
  seatAvailability: (businessId: string) => ['seats', businessId, 'availability'],
  allocations: (businessId: string, params?: unknown) => ['allocations', businessId, params ?? 'all'],
  approvals: (businessId: string, params?: unknown) => ['approvals', businessId, params ?? 'all'],
  // Owner command center (single-business + explicitly combined).
  ownerOverview: (businessId: string, params?: unknown) => ['owner', businessId, 'overview', params ?? 'all'],
  ownerRevenue: (businessId: string, params?: unknown) => ['owner', businessId, 'revenue', params ?? 'all'],
  ownerLeads: (businessId: string, params?: unknown) => ['owner', businessId, 'leads', params ?? 'all'],
  ownerCombined: (businessId: string, params?: unknown) => ['owner', businessId, 'combined', params ?? 'all'],
  // Blocks 8-12: automation / comms / AI / growth / analytics.
  autoRules: (businessId: string) => ['automation', businessId, 'rules'],
  autoExecutions: (businessId: string, params?: unknown) => ['automation', businessId, 'executions', params ?? 'all'],
  conversations: (businessId: string) => ['comms', businessId, 'conversations'],
  messages: (businessId: string, params?: unknown) => ['comms', businessId, 'messages', params ?? 'all'],
  templates: (businessId: string) => ['comms', businessId, 'templates'],
  recommendations: (businessId: string, params?: unknown) => ['ai', businessId, 'recommendations', params ?? 'all'],
  growthSources: (businessId: string) => ['growth', businessId, 'sources'],
  growthFunnel: (businessId: string) => ['growth', businessId, 'funnel'],
  referrals: (businessId: string) => ['growth', businessId, 'referrals'],
  xsell: (businessId: string) => ['growth', businessId, 'xsell'],
  metrics: (businessId: string, params?: unknown) => ['analytics', businessId, 'metrics', params ?? 'all'],
  intelligence: (businessId: string) => ['analytics', businessId, 'intelligence'],
  brief: (businessId: string) => ['owner', businessId, 'brief'],
};
