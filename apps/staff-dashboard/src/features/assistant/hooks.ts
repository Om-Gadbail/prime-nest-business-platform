import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { AIRecommendation } from '../../types';

interface Page<T> {
  items: T[];
  total: number;
}

export function useAssistant() {
  const { businessId } = useSession();
  return useMutation({
    mutationFn: (message: string) =>
      api.post<{ reply: string; tool_calls: Array<Record<string, unknown>>; escalated: boolean }>(
        '/api/v1/ai/assistant',
        { message, scope: 'business' },
      ),
    onSuccess: () => {
      void businessId;
    },
  });
}

export function useRecommendations() {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.recommendations(businessId ?? 'none'),
    queryFn: () => api.get<Page<AIRecommendation>>('/api/v1/ai/recommendations'),
    enabled: Boolean(businessId),
  });
}

export function useDecideRecommendation() {
  const { businessId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: 'approved' | 'rejected' }) =>
      api.post<{ id: string; status: string }>(`/api/v1/ai/recommendations/${id}/decide`, { decision }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.recommendations(businessId ?? 'none') });
    },
  });
}
