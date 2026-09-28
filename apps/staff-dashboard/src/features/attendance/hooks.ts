import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { Attendance, Page } from '../../types';

export interface AttendanceFilters {
  member_id?: string;
  day?: string;
  open_only?: boolean;
  limit: number;
  offset: number;
}

export function useAttendance(filters: AttendanceFilters): ReturnType<typeof useQuery<Page<Attendance>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.attendance(businessId ?? 'none', filters),
    queryFn: () =>
      api.get<Page<Attendance>>('/api/v1/attendance', {
        member_id: filters.member_id || undefined,
        day: filters.day || undefined,
        open_only: filters.open_only ? true : undefined,
        limit: filters.limit,
        offset: filters.offset,
      }),
    enabled: Boolean(businessId),
  });
}

function invalidateAttendance(client: ReturnType<typeof useQueryClient>, businessId: string): void {
  void client.invalidateQueries({ queryKey: keys.attendance(businessId) });
  void client.invalidateQueries({ queryKey: keys.ownerOverview(businessId) });
}

export function useCheckIn(): ReturnType<
  typeof useMutation<Attendance, Error, { member_id: string; attendance_date?: string; seat_id?: string; source?: string; notes?: string }>
> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Attendance>('/api/v1/attendance/check-in', body),
    onSuccess: () => {
      if (businessId) invalidateAttendance(client, businessId);
    },
  });
}

export function useCheckOut(): ReturnType<typeof useMutation<Attendance, Error, { id: string }>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id }) => api.post<Attendance>(`/api/v1/attendance/${id}/check-out`),
    onSuccess: () => {
      if (businessId) invalidateAttendance(client, businessId);
    },
  });
}
