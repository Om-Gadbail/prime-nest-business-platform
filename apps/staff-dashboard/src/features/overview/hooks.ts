import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import { useToast } from '../../components/ui/Toast';
import type { DashboardOverview, Page, AuditEvent, StatusSummary } from '../../types';

export function useOverview(): ReturnType<typeof useQuery<DashboardOverview>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.overview(businessId ?? 'none'),
    queryFn: () => api.get<DashboardOverview>('/api/v1/dashboard/overview'),
    enabled: Boolean(businessId),
    refetchInterval: 60_000,
  });
}

export function useLeadsSummary(): ReturnType<typeof useQuery<StatusSummary>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.leadsSummary(businessId ?? 'none'),
    queryFn: () => api.get<StatusSummary>('/api/v1/dashboard/leads/summary'),
    enabled: Boolean(businessId),
  });
}

export function useBookingsSummary(): ReturnType<typeof useQuery<StatusSummary>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.bookingsSummary(businessId ?? 'none'),
    queryFn: () => api.get<StatusSummary>('/api/v1/dashboard/bookings/summary'),
    enabled: Boolean(businessId),
  });
}

export function useActivityFeed(offset: number, limit = 20): ReturnType<typeof useQuery<Page<AuditEvent>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.activity(businessId ?? 'none', { offset, limit }),
    queryFn: () =>
      api.get<Page<AuditEvent>>('/api/v1/dashboard/activity', { limit, offset }),
    enabled: Boolean(businessId),
  });
}

export function useWorkload(): ReturnType<
  typeof useQuery<{ mine_open: number; mine_overdue: number; unread_notifications: number }>
> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: [...(keys.overview(businessId ?? 'none')), 'workload'],
    queryFn: () => api.get('/api/v1/dashboard/tasks'),
    enabled: Boolean(businessId),
  });
}

export function useActionFeedback(): {
  notify: (promise: Promise<unknown>, messages: { ok: string; fail: string }) => void;
  invalidate: (key: readonly unknown[]) => void;
} {
  const toast = useToast();
  const client = useQueryClient();
  return {
    notify: (promise, messages) => {
      promise.then(
        () => toast('success', messages.ok),
        (err: unknown) => toast('error', err instanceof Error ? err.message : messages.fail),
      );
    },
    invalidate: (key) => {
      void client.invalidateQueries({ queryKey: key });
    },
  };
}
