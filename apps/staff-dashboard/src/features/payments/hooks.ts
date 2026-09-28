import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { Page, Payment } from '../../types';

export interface PaymentFilters {
  member_id?: string;
  membership_id?: string;
  status?: string;
  method?: string;
  limit: number;
  offset: number;
}

export function usePayments(filters: PaymentFilters): ReturnType<typeof useQuery<Page<Payment>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.payments(businessId ?? 'none', filters),
    queryFn: () =>
      api.get<Page<Payment>>('/api/v1/payments', {
        member_id: filters.member_id || undefined,
        membership_id: filters.membership_id || undefined,
        status: filters.status || undefined,
        method: filters.method || undefined,
        limit: filters.limit,
        offset: filters.offset,
      }),
    enabled: Boolean(businessId),
  });
}

export function usePayment(id: string): ReturnType<typeof useQuery<Payment>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.payment(businessId ?? 'none', id),
    queryFn: () => api.get<Payment>(`/api/v1/payments/${id}`),
    enabled: Boolean(businessId && id),
  });
}

function invalidatePayments(client: ReturnType<typeof useQueryClient>, businessId: string, id?: string): void {
  void client.invalidateQueries({ queryKey: keys.payments(businessId) });
  void client.invalidateQueries({ queryKey: keys.memberships(businessId) });
  void client.invalidateQueries({ queryKey: keys.ownerOverview(businessId) });
  if (id) void client.invalidateQueries({ queryKey: keys.payment(businessId, id) });
}

export function useCreatePayment(): ReturnType<typeof useMutation<Payment, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Payment>('/api/v1/payments', body),
    onSuccess: () => {
      if (businessId) invalidatePayments(client, businessId);
    },
  });
}

export function useSetPaymentStatus(
  id: string,
): ReturnType<typeof useMutation<Payment, Error, { status: string }>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Payment>(`/api/v1/payments/${id}/status`, body),
    onSuccess: () => {
      if (businessId) invalidatePayments(client, businessId, id);
    },
  });
}

export function useRefundPayment(
  id: string,
): ReturnType<typeof useMutation<Payment, Error, { reason: string }>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Payment>(`/api/v1/payments/${id}/refund`, body),
    onSuccess: () => {
      if (businessId) invalidatePayments(client, businessId, id);
    },
  });
}
