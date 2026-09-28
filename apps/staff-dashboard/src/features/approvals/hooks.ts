import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { Approval, Page } from '../../types';

export interface ApprovalFilters {
  status?: string;
  limit: number;
  offset: number;
}

export function useApprovals(filters: ApprovalFilters): ReturnType<typeof useQuery<Page<Approval>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.approvals(businessId ?? 'none', filters),
    queryFn: () =>
      api.get<Page<Approval>>('/api/v1/approvals', {
        status: filters.status || undefined,
        limit: filters.limit,
        offset: filters.offset,
      }),
    enabled: Boolean(businessId),
  });
}

export function useRequestApproval(): ReturnType<typeof useMutation<Approval, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Approval>('/api/v1/approvals', body),
    onSuccess: () => {
      if (businessId) void client.invalidateQueries({ queryKey: keys.approvals(businessId) });
    },
  });
}

export function useDecideApproval(): ReturnType<
  typeof useMutation<Approval, Error, { id: string; status: string; decision_note?: string }>
> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }) => api.post<Approval>(`/api/v1/approvals/${id}/decide`, body),
    onSuccess: () => {
      if (businessId) void client.invalidateQueries({ queryKey: keys.approvals(businessId) });
    },
  });
}
