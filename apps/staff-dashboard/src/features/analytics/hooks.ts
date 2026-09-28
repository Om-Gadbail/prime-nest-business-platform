import { useQuery } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { AnalyticsMetrics, IntelligenceFinding } from '../../types';

export function useMetrics(days = 30) {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.metrics(businessId ?? 'none', { days }),
    queryFn: () => api.get<AnalyticsMetrics>('/api/v1/analytics/metrics', { days }),
    enabled: Boolean(businessId),
  });
}

export function useIntelligence(days = 30) {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.intelligence(businessId ?? 'none'),
    queryFn: () =>
      api.get<{ metrics: AnalyticsMetrics; findings: IntelligenceFinding[] }>(
        '/api/v1/analytics/intelligence',
        { days },
      ),
    enabled: Boolean(businessId),
  });
}
