import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import type { Conversation, Message, MessageTemplate } from '../../types';

interface Page<T> {
  items: T[];
  total: number;
}

export function useConversations() {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.conversations(businessId ?? 'none'),
    queryFn: () => api.get<Page<Conversation>>('/api/v1/communications/conversations'),
    enabled: Boolean(businessId),
  });
}

export function useMessages(conversationId?: string) {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.messages(businessId ?? 'none', conversationId ?? 'all'),
    queryFn: () =>
      api.get<Page<Message>>(
        '/api/v1/communications/messages',
        conversationId ? { conversation_id: conversationId } : {},
      ),
    enabled: Boolean(businessId),
  });
}

export function useTemplates() {
  const { businessId } = useSession();
  return useQuery({
    queryKey: keys.templates(businessId ?? 'none'),
    queryFn: () => api.get<Page<MessageTemplate>>('/api/v1/communications/templates'),
    enabled: Boolean(businessId),
  });
}

export function useTimeline() {
  const { businessId } = useSession();
  return useQuery({
    queryKey: ['comms', businessId ?? 'none', 'timeline'],
    queryFn: () => api.get<{ messages: Message[]; bookings: unknown[]; tasks: unknown[] }>('/api/v1/communications/timeline'),
    enabled: Boolean(businessId),
  });
}

export function useSendMessage() {
  const { businessId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { to: string; body: string; channel?: string; conversation_id?: string }) =>
      api.post<Message>('/api/v1/communications/messages', {
        channel: input.channel ?? 'whatsapp',
        to: input.to,
        body: input.body,
        conversation_id: input.conversation_id ?? null,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.messages(businessId ?? 'none') });
    },
  });
}
