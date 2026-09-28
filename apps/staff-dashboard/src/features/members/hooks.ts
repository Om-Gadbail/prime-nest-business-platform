import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { Member, Page } from '../../types';

export interface MemberFilters {
  status?: string;
  search?: string;
  limit: number;
  offset: number;
}

export interface MemberProfile {
  member: Member;
  current_membership: import('../../types').Membership | null;
  memberships: import('../../types').Membership[];
  payments: import('../../types').Payment[];
  attendance: import('../../types').Attendance[];
  renewals: import('../../types').Renewal[];
  active_seat_allocation: import('../../types').SeatAllocation | null;
}

export function useMembers(filters: MemberFilters): ReturnType<typeof useQuery<Page<Member>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.members(businessId ?? 'none', filters),
    queryFn: () =>
      api.get<Page<Member>>('/api/v1/members', {
        status: filters.status || undefined,
        search: filters.search || undefined,
        limit: filters.limit,
        offset: filters.offset,
      }),
    enabled: Boolean(businessId),
  });
}

export function useMember(id: string): ReturnType<typeof useQuery<Member>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.member(businessId ?? 'none', id),
    queryFn: () => api.get<Member>(`/api/v1/members/${id}`),
    enabled: Boolean(businessId && id),
  });
}

export function useMemberProfile(id: string): ReturnType<typeof useQuery<MemberProfile>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.memberProfile(businessId ?? 'none', id),
    queryFn: () => api.get<MemberProfile>(`/api/v1/members/${id}/profile`),
    enabled: Boolean(businessId && id),
  });
}

function invalidateMembers(client: ReturnType<typeof useQueryClient>, businessId: string, id?: string): void {
  void client.invalidateQueries({ queryKey: keys.members(businessId) });
  void client.invalidateQueries({ queryKey: keys.ownerOverview(businessId) });
  if (id) {
    void client.invalidateQueries({ queryKey: keys.member(businessId, id) });
    void client.invalidateQueries({ queryKey: keys.memberProfile(businessId, id) });
  }
}

export function useCreateMember(): ReturnType<typeof useMutation<Member, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.post<Member>('/api/v1/members', body),
    onSuccess: () => {
      if (businessId) invalidateMembers(client, businessId);
    },
  });
}

export function useUpdateMember(id: string): ReturnType<typeof useMutation<Member, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.patch<Member>(`/api/v1/members/${id}`, body),
    onSuccess: () => {
      if (businessId) invalidateMembers(client, businessId, id);
    },
  });
}
