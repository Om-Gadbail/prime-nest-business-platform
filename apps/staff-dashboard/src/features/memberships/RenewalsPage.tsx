import { useState } from 'react';
import { useRenewals } from '../memberships/hooks';
import { useListParams } from '../../lib/list';
import { Button, Card, PageHeader, StatusBadge } from '../../components/ui/primitives';
import { ErrorState, NoResults, TableSkeleton } from '../../components/ui/states';
import { Pagination, SelectInput } from '../../components/ui/forms';
import { formatDate, formatMoney, isOverdueDate } from '../../lib/list';

const STATUSES = ['', 'pending', 'confirmed', 'cancelled', 'expired'];

/** Renewals: expiring pipeline, overdue highlighting, confirm flow. */
export function RenewalsPage(): JSX.Element {
  const { limit, offset, setOffset } = useListParams();
  const [status, setStatus] = useState('pending');
  const query = useRenewals({ status, limit, offset });

  return (
    <div>
      <PageHeader title="Renewals" subtitle="Expiring and expired memberships pipeline" />
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <SelectInput label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}
            options={STATUSES.map((s) => ({ value: s, label: s === '' ? 'All statuses' : s }))} />
          <div className="flex items-end">
            <Button variant="secondary" size="sm" onClick={() => setStatus('')}>Clear</Button>
          </div>
        </div>
      </Card>
      {query.isPending ? (
        <Card><TableSkeleton /></Card>
      ) : query.isError ? (
        <ErrorState
          message={query.error instanceof Error ? query.error.message : 'Could not load renewals.'}
          onRetry={() => query.refetch()}
          title={query.error instanceof Error && /permission|forbidden/i.test(query.error.message) ? 'Not allowed' : undefined}
        />
      ) : query.data.total === 0 ? (
        <NoResults onClear={() => setStatus('')} />
      ) : (
        <Card className="p-0 sm:p-0">
          <ul className="divide-y divide-slate-100">
            {query.data.items.map((r) => {
              const overdue = r.status === 'pending' && isOverdueDate(r.due_date);
              return (
                <li key={r.id} className="flex flex-wrap items-center gap-2 px-5 py-3.5 sm:gap-3">
                  <span className="min-w-0 flex-1 basis-48">
                    <span className="block text-sm font-semibold text-slate-900">
                      Due {formatDate(r.due_date)}{overdue ? ' · overdue' : ''}
                    </span>
                    <span className="block truncate text-xs text-slate-500">
                      {formatMoney(r.renewal_amount, r.currency)}
                      {r.new_membership_id ? ' · renewed' : ''}
                    </span>
                  </span>
                  <StatusBadge status={overdue ? 'overdue' : r.status} />
                </li>
              );
            })}
          </ul>
          <div className="px-5 pb-5">
            <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />
          </div>
        </Card>
      )}
      <p className="mt-3 text-xs text-slate-500">
        Renew from the membership itself to keep history linked — the pipeline records here track outreach and due dates.
      </p>
    </div>
  );
}
