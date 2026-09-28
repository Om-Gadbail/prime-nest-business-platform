import { useState } from 'react';
import { Send } from 'lucide-react';
import { useSession } from '../../lib/auth';
import { useMessages, useSendMessage, useTemplates, useTimeline } from './hooks';
import { Badge, Button, Card, PageHeader } from '../../components/ui/primitives';
import { CardsSkeleton, EmptyState, ErrorState, ForbiddenState } from '../../components/ui/states';
import { TextArea, TextInput } from '../../components/ui/forms';

/** Communications: unified timeline, message history, templates, staff send. */
export function CommsPage(): JSX.Element {
  const { can } = useSession();
  if (!can('communications.read')) return <ForbiddenState />;

  return (
    <div>
      <PageHeader title="Communications" subtitle="Every conversation, in one timeline" />
      <div className="grid gap-4 xl:grid-cols-2">
        <TimelineCard />
        <div className="space-y-4">
          {can('communications.manage') ? <SendCard /> : null}
          <TemplatesCard />
        </div>
      </div>
    </div>
  );
}

function TimelineCard(): JSX.Element {
  const timeline = useTimeline();
  const messages = useMessages();
  if (timeline.isPending || messages.isPending) return <CardsSkeleton count={5} />;
  const err = timeline.isError ? timeline : messages.isError ? messages : null;
  if (err) {
    return (
      <ErrorState
        message={err.error instanceof Error ? err.error.message : 'Could not load messages.'}
        onRetry={() => { void timeline.refetch(); void messages.refetch(); }}
      />
    );
  }
  const items = messages.data?.items ?? [];
  if (items.length === 0) {
    return <EmptyState title="No messages yet" message="Inbound WhatsApp and automation messages appear here." />;
  }
  return (
    <Card>
      <h2 className="mb-3 text-base font-bold text-slate-900">Timeline ({messages.data?.total ?? 0})</h2>
      <ul className="max-h-[480px] space-y-2 overflow-y-auto pr-1">
        {items.slice(0, 50).map((m) => (
          <li
            key={m.id}
            className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm ring-1 ${
              m.direction === 'inbound'
                ? 'bg-white text-slate-900 ring-slate-200'
                : 'ml-auto bg-slate-900 text-white ring-slate-900'
            }`}
          >
            <span className="mb-1 flex items-center gap-2 text-[11px] opacity-70">
              <Badge>{m.channel}</Badge>
              <span>{m.direction}</span>
              <span>{m.status}</span>
            </span>
            <span className="block break-words">{m.body}</span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-slate-500">
        Bookings {(timeline.data?.bookings.length ?? 0)} · Tasks {(timeline.data?.tasks.length ?? 0)} linked in this view.
      </p>
    </Card>
  );
}

function SendCard(): JSX.Element {
  const send = useSendMessage();
  const [to, setTo] = useState('');
  const [body, setBody] = useState('');
  return (
    <Card>
      <h2 className="mb-3 text-base font-bold text-slate-900">Send message</h2>
      <div className="space-y-3">
        <TextInput label="Recipient (phone)" value={to} onChange={(e) => setTo(e.target.value)} placeholder="+91…" inputMode="tel" />
        <TextArea label="Message" value={body} onChange={(e) => setBody(e.target.value)} rows={3} placeholder="Type a message…" />
        {send.isError ? (
          <p className="text-sm text-rose-600" role="alert">
            {send.error instanceof Error ? send.error.message : 'Send failed.'}
          </p>
        ) : null}
        {send.isSuccess ? (
          <p className="text-sm text-emerald-700" role="status">Sent via {send.data.provider}.</p>
        ) : null}
        <Button loading={send.isPending} disabled={!to.trim() || !body.trim()} onClick={() => send.mutate({ to: to.trim(), body: body.trim() })}>
          <Send className="h-4 w-4" aria-hidden /> Send
        </Button>
      </div>
    </Card>
  );
}

function TemplatesCard(): JSX.Element {
  const templates = useTemplates();
  if (templates.isPending) return <CardsSkeleton count={4} />;
  if (templates.isError) {
    return (
      <ErrorState
        message={templates.error instanceof Error ? templates.error.message : 'Could not load templates.'}
        onRetry={() => templates.refetch()}
      />
    );
  }
  return (
    <Card>
      <h2 className="mb-3 text-base font-bold text-slate-900">Templates ({templates.data.total})</h2>
      <ul className="divide-y divide-slate-100">
        {templates.data.items.map((t) => (
          <li key={t.id} className="py-2">
            <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-slate-900">
              <span className="font-mono text-xs text-slate-500">{t.code}</span> {t.name}
              <Badge>{t.channel}</Badge>
            </p>
            <p className="mt-1 text-sm text-slate-600">{t.body}</p>
          </li>
        ))}
      </ul>
    </Card>
  );
}
