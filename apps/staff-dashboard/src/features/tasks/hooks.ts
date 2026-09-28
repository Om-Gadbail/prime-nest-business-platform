import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { Page, StaffTask } from '../../types';

export interface TaskFilters {
  status?: string;
  priority?: string;
  overdue_only?: boolean;
  mine_only?: boolean;
  search?: string;
  limit: number;
  offset: number;
}

export function useTasks(filters: TaskFilters): ReturnType<typeof useQuery<Page<StaffTask>>> {
  const { businessId, me } = useSession();
  const assigned = filters.mine_only ? me?.user.id : undefined;
  return useQuery({
    queryKey: keys.tasks(businessId ?? 'none', { ...filters, assigned }),
    queryFn: () =>
      api.get<Page<StaffTask>>('/api/v1/tasks', {
        status: filters.status || undefined,
        priority: filters.priority || undefined,
        overdue_only: filters.overdue_only || undefined,
        assigned_to_user_id: assigned,
        search: filters.search || undefined,
        limit: filters.limit,
        offset: filters.offset,
      }),
    enabled: Boolean(businessId),
  });
}

export function useTask(id: string): ReturnType<typeof useQuery<StaffTask>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.task(businessId ?? 'none', id),
    queryFn: () => api.get<StaffTask>(`/api/v1/tasks/${id}`),
    enabled: Boolean(businessId && id),
  });
}

function invalidateTasks(client: ReturnType<typeof useQueryClient>, businessId: string, id?: string): void {
  void client.invalidateQueries({ queryKey: keys.tasks(businessId) });
  void client.invalidateQueries({ queryKey: keys.overview(businessId) });
  if (id) void client.invalidateQueries({ queryKey: keys.task(businessId, id) });
}

export function useCreateTask(): ReturnType<typeof useMutation<StaffTask, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<StaffTask>('/api/v1/tasks', body),
    onSuccess: () => {
      if (businessId) invalidateTasks(client, businessId);
    },
  });
}

export function useUpdateTask(id: string): ReturnType<typeof useMutation<StaffTask, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.patch<StaffTask>(`/api/v1/tasks/${id}`, body),
    onSuccess: () => {
      if (businessId) invalidateTasks(client, businessId, id);
    },
  });
}

export function useAssignTask(id: string): ReturnType<typeof useMutation<StaffTask, Error, { assigned_to_user_id: string }>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<StaffTask>(`/api/v1/tasks/${id}/assign`, body),
    onSuccess: () => {
      if (businessId) {
        invalidateTasks(client, businessId, id);
        void client.invalidateQueries({ queryKey: keys.notifications(businessId) });
      }
    },
  });
}

export function useSetTaskStatus(id: string): ReturnType<typeof useMutation<StaffTask, Error, { status: string }>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<StaffTask>(`/api/v1/tasks/${id}/status`, body),
    onSuccess: () => {
      if (businessId) invalidateTasks(client, businessId, id);
    },
  });
}
