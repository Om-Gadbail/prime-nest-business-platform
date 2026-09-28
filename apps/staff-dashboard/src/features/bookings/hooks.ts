import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { Booking, Page } from '../../types';

export interface BookingFilters {
  status?: string;
  booking_type?: string;
  limit: number;
  offset: number;
}

export function useBookings(filters: BookingFilters): ReturnType<typeof useQuery<Page<Booking>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.bookings(businessId ?? 'none', filters),
    queryFn: () =>
      api.get<Page<Booking>>('/api/v1/bookings', {
        status: filters.status || undefined,
        booking_type: filters.booking_type || undefined,
        limit: filters.limit,
        offset: filters.offset,
      }),
    enabled: Boolean(businessId),
  });
}

export function useBooking(id: string): ReturnType<typeof useQuery<Booking>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.booking(businessId ?? 'none', id),
    queryFn: () => api.get<Booking>(`/api/v1/bookings/${id}`),
    enabled: Boolean(businessId && id),
  });
}

function invalidateBooking(client: ReturnType<typeof useQueryClient>, businessId: string, id?: string): void {
  void client.invalidateQueries({ queryKey: keys.bookings(businessId) });
  void client.invalidateQueries({ queryKey: keys.overview(businessId) });
  void client.invalidateQueries({ queryKey: keys.bookingsSummary(businessId) });
  if (id) void client.invalidateQueries({ queryKey: keys.booking(businessId, id) });
}

export function useCreateBooking(): ReturnType<typeof useMutation<Booking, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Booking>('/api/v1/bookings', body),
    onSuccess: () => {
      if (businessId) invalidateBooking(client, businessId);
    },
  });
}

export function useUpdateBooking(id: string): ReturnType<typeof useMutation<Booking, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.patch<Booking>(`/api/v1/bookings/${id}`, body),
    onSuccess: () => {
      if (businessId) invalidateBooking(client, businessId, id);
    },
  });
}

export function useBookingTransition(id: string): ReturnType<
  typeof useMutation<Booking, Error, { action: 'confirm' | 'cancel' | 'complete' | 'no-show' | 'reopen'; cancellation_reason?: string }>
> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ action, cancellation_reason }) =>
      api.post<Booking>(
        `/api/v1/bookings/${id}/${action}`,
        action === 'cancel' ? { cancellation_reason: cancellation_reason ?? '' } : undefined,
      ),
    onSuccess: () => {
      if (businessId) invalidateBooking(client, businessId, id);
    },
  });
}
