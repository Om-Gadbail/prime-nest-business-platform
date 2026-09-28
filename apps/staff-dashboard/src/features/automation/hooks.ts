import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { AutomationExecution, AutomationRule, DailyBrief } from '../../types';

interface Page<T> {
  items: T[];
  total: number;
}

export function useAutoRules() {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.autoRules(businessId ?? 'none'),
    queryFn: () => api.get<Page<AutomationRule>>('/api/v1/automation/rules'),
    enabled: Boolean(businessId),
  });
}

export function useAutoExecutions(status?: string) {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.autoExecutions(businessId ?? 'none', status ?? 'all'),
    queryFn: () =>
      api.get<Page<AutomationExecution>>('/api/v1/automation/executions', status ? { status } : {}),
    enabled: Boolean(businessId),
  });
}

export function useBrief() {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.brief(businessId ?? 'none'),
    queryFn: () => api.get<DailyBrief>('/api/v1/owner/brief'),
    enabled: Boolean(businessId),
  });
}

export function useRunScheduler() {
  const { businessId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ ran: number }>('/api/v1/automation/scheduler/run', {}),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.autoExecutions(businessId ?? 'none') });
    },
  });
}

export function useSeedDefaults() {
  const { businessId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ rules_created: number }>('/api/v1/automation/seed-defaults', {}),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.autoRules(businessId ?? 'none') });
    },
  });
}
