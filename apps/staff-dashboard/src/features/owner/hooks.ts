import { useQuery } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { CombinedOverview, OwnerBusinessOverview, OwnerLeadsReport, OwnerRevenueReport } from '../../types';

export type RangePreset = 'today' | '7d' | '30d' | 'month' | 'quarter' | 'all';

function rangeQuery(preset: RangePreset): Record<string, string> {
  return { preset };
}

export function useOwnerOverview(preset: RangePreset = '30d'): ReturnType<typeof useQuery<OwnerBusinessOverview>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.ownerOverview(businessId ?? 'none', { preset }),
    queryFn: () => api.get<OwnerBusinessOverview>('/api/v1/owner/overview', rangeQuery(preset)),
    enabled: Boolean(businessId),
    refetchInterval: 60_000,
  });
}

export function useOwnerRevenue(preset: RangePreset = '30d'): ReturnType<typeof useQuery<OwnerRevenueReport>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.ownerRevenue(businessId ?? 'none', { preset }),
    queryFn: () => api.get<OwnerRevenueReport>('/api/v1/owner/revenue', rangeQuery(preset)),
    enabled: Boolean(businessId),
  });
}

export function useOwnerLeads(preset: RangePreset = '30d'): ReturnType<typeof useQuery<OwnerLeadsReport>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.ownerLeads(businessId ?? 'none', { preset }),
    queryFn: () => api.get<OwnerLeadsReport>('/api/v1/owner/leads', rangeQuery(preset)),
    enabled: Boolean(businessId),
  });
}

export function useOwnerCombined(
  scope: string = 'all',
  preset: RangePreset = '30d',
): ReturnType<typeof useQuery<CombinedOverview>> {
  const { businessId, can } = useSession();
  const allowed = can('owner.combined.read');
  return useQuery({
    queryKey: keys.ownerCombined(businessId ?? 'none', { scope, preset }),
    queryFn: () =>
      api.get<CombinedOverview>('/api/v1/owner/combined', { scope, ...rangeQuery(preset) }),
    enabled: Boolean(businessId) && allowed,
    refetchInterval: 60_000,
  });
}
