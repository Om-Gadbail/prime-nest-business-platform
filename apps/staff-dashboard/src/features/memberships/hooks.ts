import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { Membership, MembershipPlan, Page, Renewal } from '../../types';

export interface PlanFilters {
  category?: string;
  activeOnly?: boolean;
  search?: string;
  limit: number;
  offset: number;
}

export interface MembershipFilters {
  member_id?: string;
  status?: string;
  payment_state?: string;
  limit: number;
  offset: number;
}

export interface RenewalFilters {
  member_id?: string;
  status?: string;
  limit: number;
  offset: number;
}

export function usePlans(filters: PlanFilters): ReturnType<typeof useQuery<Page<MembershipPlan>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.plans(businessId ?? 'none', filters),
    queryFn: () =>
      api.get<Page<MembershipPlan>>('/api/v1/membership-plans', {
        category: filters.category || undefined,
        is_active: filters.activeOnly ? true : undefined,
        search: filters.search || undefined,
        limit: filters.limit,
        offset: filters.offset,
      }),
    enabled: Boolean(businessId),
  });
}

export function useMemberships(filters: MembershipFilters): ReturnType<typeof useQuery<Page<Membership>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.memberships(businessId ?? 'none', filters),
    queryFn: () =>
      api.get<Page<Membership>>('/api/v1/memberships', {
        member_id: filters.member_id || undefined,
        status: filters.status || undefined,
        payment_state: filters.payment_state || undefined,
        limit: filters.limit,
        offset: filters.offset,
      }),
    enabled: Boolean(businessId),
  });
}

export function useMembership(id: string): ReturnType<typeof useQuery<Membership>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.membership(businessId ?? 'none', id),
    queryFn: () => api.get<Membership>(`/api/v1/memberships/${id}`),
    enabled: Boolean(businessId && id),
  });
}

export function useRenewals(filters: RenewalFilters): ReturnType<typeof useQuery<Page<Renewal>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.renewals(businessId ?? 'none', filters),
    queryFn: () =>
      api.get<Page<Renewal>>('/api/v1/renewals', {
        member_id: filters.member_id || undefined,
        status: filters.status || undefined,
        limit: filters.limit,
        offset: filters.offset,
      }),
    enabled: Boolean(businessId),
  });
}

function invalidateOps(client: ReturnType<typeof useQueryClient>, businessId: string): void {
  void client.invalidateQueries({ queryKey: keys.memberships(businessId) });
  void client.invalidateQueries({ queryKey: keys.plans(businessId) });
  void client.invalidateQueries({ queryKey: keys.renewals(businessId) });
  void client.invalidateQueries({ queryKey: keys.members(businessId) });
  void client.invalidateQueries({ queryKey: keys.ownerOverview(businessId) });
}

export function useCreatePlan(): ReturnType<typeof useMutation<MembershipPlan, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<MembershipPlan>('/api/v1/membership-plans', body),
    onSuccess: () => {
      if (businessId) invalidateOps(client, businessId);
    },
  });
}

export function useUpdatePlan(id: string): ReturnType<typeof useMutation<MembershipPlan, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.patch<MembershipPlan>(`/api/v1/membership-plans/${id}`, body),
    onSuccess: () => {
      if (businessId) invalidateOps(client, businessId);
    },
  });
}

export function useCreateMembership(): ReturnType<typeof useMutation<Membership, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Membership>('/api/v1/memberships', body),
    onSuccess: () => {
      if (businessId) invalidateOps(client, businessId);
    },
  });
}

export function useSetMembershipStatus(
  id: string,
): ReturnType<typeof useMutation<Membership, Error, { status: string; cancel_reason?: string }>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Membership>(`/api/v1/memberships/${id}/status`, body),
    onSuccess: () => {
      if (businessId) {
        invalidateOps(client, businessId);
        void client.invalidateQueries({ queryKey: keys.membership(businessId, id) });
      }
    },
  });
}

export function useRenewMembership(
  id: string,
): ReturnType<typeof useMutation<Membership, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Membership>(`/api/v1/memberships/${id}/renew`, body),
    onSuccess: () => {
      if (businessId) invalidateOps(client, businessId);
    },
  });
}

export function useCreateRenewal(): ReturnType<typeof useMutation<Renewal, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Renewal>('/api/v1/renewals', body),
    onSuccess: () => {
      if (businessId) invalidateOps(client, businessId);
    },
  });
}
