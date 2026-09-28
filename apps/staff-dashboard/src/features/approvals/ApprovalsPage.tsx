import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useSession } from '../../lib/auth';
import { useApprovals, useDecideApproval } from './hooks';
import { useListParams } from '../../lib/list';
import { Button, Card, PageHeader, StatusBadge } from '../../components/ui/primitives';
import { Modal } from '../../components/ui/overlays';
import { ErrorState, NoResults, TableSkeleton } from '../../components/ui/states';
import { Pagination, SelectInput, TextArea } from '../../components/ui/forms';
import { useToast } from '../../components/ui/Toast';
import { formatDateTime } from '../../lib/list';
import type { Approval } from '../../types';

const STATUSES = ['', 'pending', 'approved', 'rejected', 'cancelled', 'expired'];

/** Approvals: request review, owner/admin decide. Requesters can't self-decide. */
export function ApprovalsPage(): JSX.Element {
  const { can } = useSession();
  const manageable = can('approvals.manage');
  const { limit, offset, setOffset } = useListParams();
  const [status, setStatus] = useState('pending');
  const [decideTarget, setDecideTarget] = useState<{ approval: Approval; decision: string } | null>(null);
  const query = useApprovals({ status, limit, offset });

  return (
    <div>
      <PageHeader title="Approvals" subtitle="Sensitive operations need explicit sign-off" />
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
        <ErrorState message={query.error instanceof Error ? query.error.message : 'Could not load approvals.'} onRetry={() => query.refetch()} />
      ) : query.data.total === 0 ? (
        <NoResults onClear={() => setStatus('')} />
      ) : (
        <Card className="p-0 sm:p-0">
          <ul className="divide-y divide-slate-100">
            {query.data.items.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-2 px-5 py-3.5 sm:gap-3">
                <span className="min-w-0 flex-1 basis-48">
                  <span className="block truncate text-sm font-semibold text-slate-900">{a.title || a.entity_type}</span>
                  <span className="block truncate text-xs text-slate-500">
                    {a.action} · {a.entity_type} · {formatDateTime(a.created_at)}
                  </span>
                </span>
                <StatusBadge status={a.status} />
                {manageable && a.status === 'pending' ? (
                  <span className="flex w-full gap-2 sm:w-auto">
                    <Button size="sm" variant="secondary" onClick={() => setDecideTarget({ approval: a, decision: 'approved' })}>Approve</Button>
                    <Button size="sm" variant="ghost" onClick={() => setDecideTarget({ approval: a, decision: 'rejected' })}>Reject</Button>
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
          <div className="px-5 pb-5">
            <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />
          </div>
        </Card>
      )}
      <DecideModal target={decideTarget} onClose={() => setDecideTarget(null)} />
    </div>
  );
}

function DecideModal({
  target,
  onClose,
}: {
  target: { approval: Approval; decision: string } | null;
  onClose: () => void;
}): JSX.Element {
  const toast = useToast();
  const decide = useDecideApproval();
  const { register, handleSubmit, reset } = useForm({ defaultValues: { decision_note: '' } });
  const onSubmit = handleSubmit((values: { decision_note: string }) => {
    if (!target) return;
    decide.mutate(
      { id: target.approval.id, status: target.decision, decision_note: values.decision_note.trim() },
      {
        onSuccess: () => { toast('success', `Approval ${target.decision}.`); reset(); onClose(); },
        onError: (err) => toast('error', err.message),
      },
    );
  });
  return (
    <Modal open={Boolean(target)} onClose={onClose} title={target ? `${target.decision === 'approved' ? 'Approve' : 'Reject'}: ${target.approval.title}` : 'Decide'}>
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <TextArea label="Decision note (optional)" {...register('decision_note')} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Back</Button>
          <Button type="submit" loading={decide.isPending} variant={target?.decision === 'approved' ? 'primary' : 'danger'}>
            Confirm {target?.decision}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
