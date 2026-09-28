import { Link } from 'react-router-dom';
import { useSession } from '../../lib/auth';
import { useActivityFeed } from '../overview/hooks';
import { useListParams, formatDateTime } from '../../lib/list';
import { Card, PageHeader } from '../../components/ui/primitives';
import { ErrorState, ForbiddenState, TableSkeleton } from '../../components/ui/states';
import { Pagination } from '../../components/ui/forms';

/** Staff activity: durable audit trail (business-scoped, append-only). */
export function ActivityPage(): JSX.Element {
  const { can } = useSession();
  const { limit, offset, setOffset } = useListParams();
  const feed = useActivityFeed(offset, limit);

  if (!can('audit.read')) {
    return (
      <div>
        <PageHeader title="Activity" />
        <ForbiddenState />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="Activity" subtitle="Who did what, when — audit trail (read-only)" />
      {feed.isPending ? (
        <Card><TableSkeleton /></Card>
      ) : feed.isError ? (
        <ErrorState message={feed.error instanceof Error ? feed.error.message : 'Could not load activity.'} onRetry={() => feed.refetch()} />
      ) : feed.data.total === 0 ? (
        <Card><p className="py-6 text-center text-sm text-slate-500">No activity recorded yet.</p></Card>
      ) : (
        <Card className="p-0 sm:p-0">
          <ol className="divide-y divide-slate-100">
            {feed.data.items.map((e) => (
              <li key={e.id} className="px-5 py-3.5">
                <p className="text-sm font-semibold text-slate-900">{describe(e.action)}</p>
                <p className="mt-0.5 text-xs text-slate-500">
                  {formatDateTime(e.created_at)}
                  {e.actor_user_id ? ` · by ${e.actor_user_id.slice(0, 8)}…` : ' · system'}
                  {e.result !== 'success' ? ` · ${e.result}` : ''}
                </p>
                {e.entity_type && e.entity_id ? <EntityLink type={e.entity_type} id={e.entity_id} /> : null}
              </li>
            ))}
          </ol>
          <div className="px-5 pb-5">
            <Pagination total={feed.data.total} limit={limit} offset={offset} onChange={setOffset} />
          </div>
        </Card>
      )}
    </div>
  );
}

function describe(action: string): string {
  return action.replace(/\./g, ' · ').replace(/_/g, ' ');
}

function EntityLink({ type, id }: { type: string; id: string }): JSX.Element | null {
  const to =
    type === 'lead' ? `/leads/${id}`
    : type === 'booking' ? `/bookings/${id}`
    : type === 'task' ? `/tasks/${id}`
    : type === 'contact' ? `/contacts/${id}`
    : type === 'customer' ? `/customers/${id}`
    : null;
  if (!to) return null;
  return (
    <Link to={to} className="mt-1 inline-block text-xs font-semibold text-slate-600 underline decoration-slate-300 underline-offset-2 hover:text-slate-900">
      Open {type} →
    </Link>
  );
}
