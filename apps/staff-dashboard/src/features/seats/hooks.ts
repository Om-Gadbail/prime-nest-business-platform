import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { Page, Seat, SeatAllocation, SeatArea, SeatAvailability } from '../../types';

export interface SeatFilters {
  status?: string;
  seat_type?: string;
  search?: string;
  limit: number;
  offset: number;
}

export interface AllocationFilters {
  status?: string;
  member_id?: string;
  limit: number;
  offset: number;
}

export function useSeatAreas(): ReturnType<typeof useQuery<Page<SeatArea>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.seatAreas(businessId ?? 'none'),
    queryFn: () => api.get<Page<SeatArea>>('/api/v1/seat-areas', { limit: 100 }),
    enabled: Boolean(businessId),
  });
}

export function useSeats(filters: SeatFilters): ReturnType<typeof useQuery<Page<Seat>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.seats(businessId ?? 'none', filters),
    queryFn: () =>
      api.get<Page<Seat>>('/api/v1/seats', {
        status: filters.status || undefined,
        seat_type: filters.seat_type || undefined,
        search: filters.search || undefined,
        limit: filters.limit,
        offset: filters.offset,
      }),
    enabled: Boolean(businessId),
  });
}

export function useSeatAvailability(): ReturnType<typeof useQuery<SeatAvailability>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.seatAvailability(businessId ?? 'none'),
    queryFn: () => api.get<SeatAvailability>('/api/v1/seats/availability'),
    enabled: Boolean(businessId),
    refetchInterval: 30_000,
  });
}

export function useFreeSeats(seatType?: string): ReturnType<typeof useQuery<{ items: Seat[]; total: number }>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.seats(businessId ?? 'none', { free: true, seatType }),
    queryFn: () =>
      api.get<{ items: Seat[]; total: number }>('/api/v1/seats/available', {
        seat_type: seatType || undefined,
        limit: 100,
      }),
    enabled: Boolean(businessId),
  });
}

export function useAllocations(filters: AllocationFilters): ReturnType<typeof useQuery<Page<SeatAllocation>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.allocations(businessId ?? 'none', filters),
    queryFn: () =>
      api.get<Page<SeatAllocation>>('/api/v1/seat-allocations', {
        status: filters.status || undefined,
        member_id: filters.member_id || undefined,
        limit: filters.limit,
        offset: filters.offset,
      }),
    enabled: Boolean(businessId),
  });
}

function invalidateSeats(client: ReturnType<typeof useQueryClient>, businessId: string): void {
  void client.invalidateQueries({ queryKey: keys.seats(businessId) });
  void client.invalidateQueries({ queryKey: keys.seatAvailability(businessId) });
  void client.invalidateQueries({ queryKey: keys.allocations(businessId) });
  void client.invalidateQueries({ queryKey: keys.ownerOverview(businessId) });
}

export function useCreateSeat(): ReturnType<typeof useMutation<Seat, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Seat>('/api/v1/seats', body),
    onSuccess: () => {
      if (businessId) invalidateSeats(client, businessId);
    },
  });
}

export function useAllocateSeat(): ReturnType<
  typeof useMutation<SeatAllocation, Error, { seat_id: string; member_id: string; membership_id?: string; notes?: string }>
> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<SeatAllocation>('/api/v1/seat-allocations', body),
    onSuccess: () => {
      if (businessId) invalidateSeats(client, businessId);
    },
  });
}

export function useReleaseSeat(): ReturnType<typeof useMutation<SeatAllocation, Error, { id: string }>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id }) => api.post<SeatAllocation>(`/api/v1/seat-allocations/${id}/release`),
    onSuccess: () => {
      if (businessId) invalidateSeats(client, businessId);
    },
  });
}

export function useTransferSeat(): ReturnType<
  typeof useMutation<SeatAllocation, Error, { id: string; to_member_id: string }>
> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, to_member_id }) =>
      api.post<SeatAllocation>(`/api/v1/seat-allocations/${id}/transfer`, { to_member_id }),
    onSuccess: () => {
      if (businessId) invalidateSeats(client, businessId);
    },
  });
}
