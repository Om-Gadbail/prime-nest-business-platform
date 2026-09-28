import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { Page, StaffNotification } from '../../types';

export function useNotifications(unreadOnly: boolean, offset: number, limit = 20): ReturnType<typeof useQuery<Page<StaffNotification>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.notifications(businessId ?? 'none', { unreadOnly, offset, limit }),
    queryFn: () =>
      api.get<Page<StaffNotification>>('/api/v1/notifications', { unread_only: unreadOnly, limit, offset }),
    enabled: Boolean(businessId),
    refetchInterval: 60_000,
  });
}

export function useUnreadCount(businessId: string): ReturnType<typeof useQuery<number>> {
  return useQuery({
    queryKey: keys.unreadCount(businessId || 'none'),
    queryFn: async () => {
      const data = await api.get<{ unread: number }>('/api/v1/notifications/unread-count');
      return data.unread;
    },
    enabled: Boolean(businessId),
    refetchInterval: 60_000,
  });
}

export function useMarkRead(): ReturnType<typeof useMutation<StaffNotification, Error, string>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id) => api.post<StaffNotification>(`/api/v1/notifications/${id}/read`),
    onSuccess: () => {
      if (businessId) {
        void client.invalidateQueries({ queryKey: keys.notifications(businessId) });
        void client.invalidateQueries({ queryKey: keys.overview(businessId) });
      }
    },
  });
}

export function useMarkAllRead(): ReturnType<typeof useMutation<{ marked: number }, Error, void>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ marked: number }>('/api/v1/notifications/read-all'),
    onSuccess: () => {
      if (businessId) {
        void client.invalidateQueries({ queryKey: keys.notifications(businessId) });
        void client.invalidateQueries({ queryKey: keys.overview(businessId) });
      }
    },
  });
}

export function useSetPreference(): ReturnType<
  typeof useMutation<{ notification_type: string; enabled: boolean }, Error, { type: string; enabled: boolean }>
> {
  return useMutation({
    mutationFn: ({ type, enabled }) =>
      api.put<{ notification_type: string; enabled: boolean }>(`/api/v1/notifications/preferences/${type}`, { enabled }),
  });
}
