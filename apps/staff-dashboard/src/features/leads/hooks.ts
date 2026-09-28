import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { Customer, Lead, LeadActivity, Page } from '../../types';

export interface LeadFilters {
  status?: string;
  source?: string;
  search?: string;
  limit: number;
  offset: number;
}

export function useLeads(filters: LeadFilters): ReturnType<typeof useQuery<Page<Lead>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.leads(businessId ?? 'none', filters),
    queryFn: () =>
      api.get<Page<Lead>>('/api/v1/leads', {
        status: filters.status || undefined,
        source: filters.source || undefined,
        search: filters.search || undefined,
        limit: filters.limit,
        offset: filters.offset,
      }),
    enabled: Boolean(businessId),
  });
}

export function useLead(id: string): ReturnType<typeof useQuery<Lead>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.lead(businessId ?? 'none', id),
    queryFn: () => api.get<Lead>(`/api/v1/leads/${id}`),
    enabled: Boolean(businessId && id),
  });
}

export function useLeadActivities(id: string): ReturnType<typeof useQuery<Page<LeadActivity>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.leadActivities(businessId ?? 'none', id),
    queryFn: () => api.get<Page<LeadActivity>>(`/api/v1/leads/${id}/activities`, { limit: 50 }),
    enabled: Boolean(businessId && id),
  });
}

function invalidateLead(client: ReturnType<typeof useQueryClient>, businessId: string, id?: string): void {
  void client.invalidateQueries({ queryKey: keys.leads(businessId) });
  void client.invalidateQueries({ queryKey: keys.overview(businessId) });
  void client.invalidateQueries({ queryKey: keys.leadsSummary(businessId) });
  if (id) {
    void client.invalidateQueries({ queryKey: keys.lead(businessId, id) });
    void client.invalidateQueries({ queryKey: keys.leadActivities(businessId, id) });
  }
}

export function useCreateLead(): ReturnType<typeof useMutation<Lead, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Lead>('/api/v1/leads', body),
    onSuccess: () => {
      if (businessId) invalidateLead(client, businessId);
    },
  });
}

export function useUpdateLead(id: string): ReturnType<typeof useMutation<Lead, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.patch<Lead>(`/api/v1/leads/${id}`, body),
    onSuccess: () => {
      if (businessId) invalidateLead(client, businessId, id);
    },
  });
}

export function useAssignLead(id: string): ReturnType<typeof useMutation<Lead, Error, { assigned_user_id: string }>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Lead>(`/api/v1/leads/${id}/assign`, body),
    onSuccess: () => {
      if (businessId) {
        invalidateLead(client, businessId, id);
        void client.invalidateQueries({ queryKey: keys.notifications(businessId) });
      }
    },
  });
}

export function useSetLeadStatus(id: string): ReturnType<
  typeof useMutation<Lead, Error, { status: string; lost_reason?: string; note?: string }>
> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Lead>(`/api/v1/leads/${id}/status`, body),
    onSuccess: () => {
      if (businessId) invalidateLead(client, businessId, id);
    },
  });
}

export function useAddLeadNote(id: string): ReturnType<
  typeof useMutation<LeadActivity, Error, { note: string; activity_type?: string }>
> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<LeadActivity>(`/api/v1/leads/${id}/notes`, body),
    onSuccess: () => {
      if (businessId) invalidateLead(client, businessId, id);
    },
  });
}

export function useConvertLead(id: string): ReturnType<
  typeof useMutation<Customer, Error, { customer_notes?: string }>
> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Customer>(`/api/v1/leads/${id}/convert`, body),
    onSuccess: () => {
      if (businessId) {
        invalidateLead(client, businessId, id);
        void client.invalidateQueries({ queryKey: keys.customers(businessId) });
      }
    },
  });
}

export function useTransferLead(id: string): ReturnType<
  typeof useMutation<Lead, Error, { target_business_slug: string; reason: string }>
> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Lead>(`/api/v1/leads/${id}/transfer`, body),
    onSuccess: () => {
      if (businessId) invalidateLead(client, businessId, id);
    },
  });
}
