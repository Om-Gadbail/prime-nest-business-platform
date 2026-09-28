import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { Contact, Customer, Page, PersonView } from '../../types';

export interface ContactFilters {
  search?: string;
  status?: string;
  limit: number;
  offset: number;
}

export function useContacts(filters: ContactFilters): ReturnType<typeof useQuery<Page<Contact>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.contacts(businessId ?? 'none', filters),
    queryFn: () =>
      api.get<Page<Contact>>('/api/v1/contacts', {
        search: filters.search || undefined,
        status: filters.status || undefined,
        limit: filters.limit,
        offset: filters.offset,
      }),
    enabled: Boolean(businessId),
  });
}

export function useContact(id: string): ReturnType<typeof useQuery<Contact>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.contact(businessId ?? 'none', id),
    queryFn: () => api.get<Contact>(`/api/v1/contacts/${id}`),
    enabled: Boolean(businessId && id),
  });
}

export function useUpdateContact(id: string): ReturnType<typeof useMutation<Contact, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.patch<Contact>(`/api/v1/contacts/${id}`, body),
    onSuccess: () => {
      if (businessId) {
        void client.invalidateQueries({ queryKey: keys.contacts(businessId) });
        void client.invalidateQueries({ queryKey: keys.contact(businessId, id) });
      }
    },
  });
}

export function useCustomers(status: string, limit: number, offset: number): ReturnType<typeof useQuery<Page<Customer>>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.customers(businessId ?? 'none', { status, limit, offset }),
    queryFn: () =>
      api.get<Page<Customer>>('/api/v1/customers', {
        status: status || undefined,
        limit,
        offset,
      }),
    enabled: Boolean(businessId),
  });
}

export function useCustomer(id: string): ReturnType<typeof useQuery<Customer>> {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.customer(businessId ?? 'none', id),
    queryFn: () => api.get<Customer>(`/api/v1/customers/${id}`),
    enabled: Boolean(businessId && id),
  });
}

export function useUpdateCustomer(id: string): ReturnType<typeof useMutation<Customer, Error, Record<string, unknown>>> {
  const { businessId } = useSession();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.patch<Customer>(`/api/v1/customers/${id}`, body),
    onSuccess: () => {
      if (businessId) {
        void client.invalidateQueries({ queryKey: keys.customers(businessId) });
        void client.invalidateQueries({ queryKey: keys.customer(businessId, id) });
      }
    },
  });
}

export function usePerson(personId: string): ReturnType<typeof useQuery<PersonView>> {
  const { businessId, can } = useSession();
  return useQuery({
    queryKey: ['identity', businessId, personId],
    queryFn: () => api.get<PersonView>(`/api/v1/identity/persons/${personId}`),
    enabled: Boolean(businessId && personId && can('contacts.read')),
  });
}
