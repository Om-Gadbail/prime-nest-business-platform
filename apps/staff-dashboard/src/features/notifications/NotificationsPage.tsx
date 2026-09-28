import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useSession } from '../../lib/auth';
import { useMarkAllRead, useMarkRead, useNotifications, useSetPreference } from './hooks';
import { useListParams, formatDateTime } from '../../lib/list';
import { Badge, Button, Card, PageHeader } from '../../components/ui/primitives';
import { EmptyState, ErrorState, TableSkeleton } from '../../components/ui/states';
import { Pagination } from '../../components/ui/forms';
import { useToast } from '../../components/ui/Toast';

const PREF_TYPES = ['new_lead', 'new_booking', 'lead_assigned', 'lead_follow_up', 'task_assigned', 'task_completed', 'system', 'ai_insight'];

/** Notification center: unread list, mark read, preferences. */
export function NotificationsPage(): JSX.Element {
  const { can } = useSession();
  const toast = useToast();
  const { limit, offset, setOffset } = useListParams();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const query = useNotifications(unreadOnly, offset, limit);
  const markRead = useMarkRead();
  const markAll = useMarkAllRead();
  const setPref = useSetPreference();
  const [prefs, setPrefs] = useState<Record<string, boolean>>({});

  return (
    <div>
      <PageHeader
        title="Notifications"
        subtitle="In-app operational inbox"
        actions={
          <Button
            size="sm"
            variant="secondary"
            onClick={() => markAll.mutate(undefined, {
              onSuccess: (r) => toast('success', `${r.marked} marked as read.`),
              onError: (e) => toast('error', e.message),
            })}
            loading={markAll.isPending}
          >
            Mark all read
          </Button>
        }
      />
      <div role="tablist" aria-label="Inbox filter" className="mb-4 flex gap-2">
        {([false, true] as const).map((v) => (
          <button
            key={String(v)}
            role="tab"
            aria-selected={unreadOnly === v}
            onClick={() => { setUnreadOnly(v); setOffset(0); }}
            className={`h-10 cursor-pointer rounded-xl px-4 text-sm font-semibold ring-1 transition ${
              unreadOnly === v ? 'bg-slate-900 text-white ring-slate-900' : 'bg-white text-slate-600 ring-slate-300 hover:bg-slate-50'
            }`}
          >
            {v ? 'Unread only' : 'All'}
          </button>
        ))}
      </div>
      {query.isPending ? (
        <Card><TableSkeleton /></Card>
      ) : query.isError ? (
        <ErrorState message={query.error instanceof Error ? query.error.message : 'Could not load notifications.'} onRetry={() => query.refetch()} />
      ) : query.data.total === 0 ? (
        <EmptyState title={unreadOnly ? 'All caught up' : 'No notifications'} message={unreadOnly ? 'Nothing unread. New leads, bookings, and assignments will appear here.' : 'Operational events will appear here.'} />
      ) : (
        <Card className="p-0 sm:p-0">
          <ul className="divide-y divide-slate-100">
            {query.data.items.map((n) => (
              <li key={n.id} className={`px-5 py-3.5 ${n.read_at ? '' : 'bg-sky-50/50'}`}>
                <div className="flex flex-wrap items-start gap-2">
                  <div className="min-w-0 flex-1 basis-56">
                    <p className="text-sm font-semibold text-slate-900">{n.title}</p>
                    {n.body ? <p className="mt-0.5 text-sm text-slate-600">{n.body}</p> : null}
                    <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                      <Badge tone={n.severity === 'info' ? 'slate' : n.severity === 'warning' ? 'amber' : 'rose'}>{n.notification_type.replace(/_/g, ' ')}</Badge>
                      {formatDateTime(n.created_at)}
                      {n.source_type && n.source_id ? <ResourceLink type={n.source_type} id={n.source_id} /> : null}
                    </p>
                  </div>
                  {n.read_at ? null : (
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={markRead.isPending}
                      onClick={() => markRead.mutate(n.id, { onError: (e) => toast('error', e.message) })}
                    >
                      Mark read
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
          <div className="px-5 pb-5">
            <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />
          </div>
        </Card>
      )}

      {can('notifications.update') ? (
        <Card className="mt-4">
          <h2 className="mb-1 text-base font-bold text-slate-900">Preferences</h2>
          <p className="mb-3 text-sm text-slate-500">Opt out of notification types you do not need. Opt-outs are respected by the backend fan-out.</p>
          <ul className="grid gap-2 sm:grid-cols-2">
            {PREF_TYPES.map((t) => (
              <li key={t} className="flex min-h-[48px] items-center justify-between gap-3 rounded-xl bg-slate-50 px-3.5 ring-1 ring-slate-200/60">
                <span className="text-sm font-medium text-slate-700">{t.replace(/_/g, ' ')}</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={prefs[t] ?? true}
                  aria-label={`Toggle ${t}`}
                  onClick={() => {
                    const next = !(prefs[t] ?? true);
                    setPrefs((p) => ({ ...p, [t]: next }));
                    setPref.mutate(
                      { type: t, enabled: next },
                      { onError: (e) => { toast('error', e.message); setPrefs((p) => ({ ...p, [t]: !next })); } },
                    );
                  }}
                  className={`relative h-7 w-12 shrink-0 cursor-pointer rounded-full transition ${(prefs[t] ?? true) ? 'bg-emerald-500' : 'bg-slate-300'}`}
                >
                  <span
                    aria-hidden
                    className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition-all ${(prefs[t] ?? true) ? 'left-5' : 'left-0.5'}`}
                  />
                </button>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}

function ResourceLink({ type, id }: { type: string; id: string }): JSX.Element | null {
  const to =
    type === 'lead' ? `/leads/${id}`
    : type === 'booking' ? `/bookings/${id}`
    : type === 'task' ? `/tasks/${id}`
    : null;
  if (!to) return null;
  return <Link to={to} className="font-semibold text-slate-600 underline decoration-slate-300 underline-offset-2 hover:text-slate-900">Open →</Link>;
}
