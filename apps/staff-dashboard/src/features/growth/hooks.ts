import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { GrowthSource } from '../../types';

interface Page<T> {
  items: T[];
  total: number;
}

export interface Referral {
  id: string;
  referrer_name: string;
  referred_name: string;
  status: string;
}

export interface CrossSell {
  id: string;
  target_business_id: string | null;
  status: string;
  consent: boolean;
  offer: string;
}

export function useSources() {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.growthSources(businessId ?? 'none'),
    queryFn: () => api.get<{ items: GrowthSource[] }>('/api/v1/growth/sources'),
    enabled: Boolean(businessId),
  });
}

export function useFunnel() {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.growthFunnel(businessId ?? 'none'),
    queryFn: () =>
      api.get<{ funnel: Record<string, { leads: number; converted: number }> }>('/api/v1/growth/funnel'),
    enabled: Boolean(businessId),
  });
}

export function useReferrals() {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.referrals(businessId ?? 'none'),
    queryFn: () => api.get<Page<Referral>>('/api/v1/growth/referrals'),
    enabled: Boolean(businessId),
  });
}

export function useCrossSell() {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.xsell(businessId ?? 'none'),
    queryFn: () => api.get<Page<CrossSell>>('/api/v1/growth/cross-sell'),
    enabled: Boolean(businessId),
  });
}

export function useCreateReferral() {
  const { businessId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { referrer_name: string; referred_name: string; referred_phone?: string }) =>
      api.post<Referral>('/api/v1/growth/referrals', { ...input, consent: true }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.referrals(businessId ?? 'none') });
    },
  });
}
