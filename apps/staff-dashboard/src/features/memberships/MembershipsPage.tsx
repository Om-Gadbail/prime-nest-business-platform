import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { Plus } from 'lucide-react';
import { useSession } from '../../lib/auth';
import { useCreateMembership, useMemberships, useRenewMembership, useSetMembershipStatus } from './hooks';
import { useMembers } from '../members/hooks';
import { useListParams } from '../../lib/list';
import { Badge, Button, Card, PageHeader, StatusBadge } from '../../components/ui/primitives';
import { ConfirmDialog, Modal } from '../../components/ui/overlays';
import { ErrorState, NoResults, TableSkeleton } from '../../components/ui/states';
import { Pagination, SelectInput, TextInput } from '../../components/ui/forms';
import { useToast } from '../../components/ui/Toast';
import { formatDate, formatMoney } from '../../lib/list';
import type { Membership } from '../../types';

const STATUSES = ['', 'pending', 'active', 'expired', 'cancelled', 'suspended'];
const PAY_STATES = ['', 'unpaid', 'pending', 'partially_paid', 'paid', 'overdue', 'failed', 'refunded', 'cancelled'];

/** Memberships: list, filters, enrol, status changes, renewals. */
export function MembershipsPage(): JSX.Element {
  const { can } = useSession();
  const { limit, offset, setOffset } = useListParams();
  const [status, setStatus] = useState('');
  const [paymentState, setPaymentState] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [renewTarget, setRenewTarget] = useState<Membership | null>(null);
  const [cancelTarget, setCancelTarget] = useState<Membership | null>(null);
  const query = useMemberships({ status, payment_state: paymentState, limit, offset });

  return (
    <div>
      <PageHeader
        title="Memberships"
        subtitle="Enrolments with lifecycle and payment state"
        actions={
          can('memberships.create') ? (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden /> New membership
            </Button>
          ) : undefined
        }
      />
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <SelectInput label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}
            options={STATUSES.map((s) => ({ value: s, label: s === '' ? 'All statuses' : s }))} />
          <SelectInput label="Payment" value={paymentState} onChange={(e) => { setPaymentState(e.target.value); setOffset(0); }}
            options={PAY_STATES.map((s) => ({ value: s, label: s === '' ? 'All states' : s.replace(/_/g, ' ') }))} />
          <div className="flex items-end">
            <Button variant="secondary" size="sm" onClick={() => { setStatus(''); setPaymentState(''); }}>Clear</Button>
          </div>
        </div>
      </Card>
      {query.isPending ? (
        <Card><TableSkeleton /></Card>
      ) : query.isError ? (
        <ErrorState message={query.error instanceof Error ? query.error.message : 'Could not load memberships.'} onRetry={() => query.refetch()} />
      ) : query.data.total === 0 ? (
        <NoResults onClear={() => { setStatus(''); setPaymentState(''); }} />
      ) : (
        <Card className="p-0 sm:p-0">
          <ul className="divide-y divide-slate-100">
            {query.data.items.map((ms) => (
              <li key={ms.id} className="flex flex-wrap items-center gap-2 px-5 py-3.5 sm:gap-3">
                <span className="min-w-0 flex-1 basis-48">
                  <span className="block truncate text-sm font-semibold text-slate-900">
                    {ms.plan_name_snapshot || 'Custom plan'}
                  </span>
                  <span className="block truncate text-xs text-slate-500">
                    {formatDate(ms.start_date)} → {formatDate(ms.end_date)} · {formatMoney(ms.final_amount, ms.currency)}
                  </span>
                </span>
                <StatusBadge status={ms.status} />
                <Badge>{ms.payment_state.replace(/_/g, ' ')}</Badge>
                <span className="flex w-full gap-2 sm:w-auto">
                  {can('memberships.update') && (ms.status === 'active' || ms.status === 'pending' || ms.status === 'expired') ? (
                    <Button size="sm" variant="secondary" onClick={() => setRenewTarget(ms)}>Renew</Button>
                  ) : null}
                  {can('memberships.update') && (ms.status === 'active' || ms.status === 'pending' || ms.status === 'suspended') ? (
                    <Button size="sm" variant="ghost" onClick={() => setCancelTarget(ms)}>Cancel</Button>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
          <div className="px-5 pb-5">
            <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />
          </div>
        </Card>
      )}
      <CreateMembershipModal open={createOpen} onClose={() => setCreateOpen(false)} />
      <RenewDialog target={renewTarget} onClose={() => setRenewTarget(null)} />
      <CancelDialog target={cancelTarget} onClose={() => setCancelTarget(null)} />
      <p className="mt-3 text-xs text-slate-500">
        Expiring soon? <Link to="/renewals" className="font-semibold text-slate-700 hover:text-slate-900">Open the renewal pipeline →</Link>
      </p>
    </div>
  );
}

function CreateMembershipModal({ open, onClose }: { open: boolean; onClose: () => void }): JSX.Element {
  const toast = useToast();
  const create = useCreateMembership();
  const members = useMembers({ limit: 100, offset: 0 });
  const { register, handleSubmit, reset } = useForm({
    defaultValues: { member_id: '', plan_id: '', start_date: '', end_date: '', price: '', discount: '', notes: '' },
  });
  const onSubmit = handleSubmit((values) => {
    const body: Record<string, unknown> = {
      member_id: values.member_id,
      plan_id: values.plan_id || null,
      start_date: values.start_date || null,
      end_date: values.end_date || null,
      price: values.price || null,
      discount: values.discount || null,
      notes: (values.notes ?? '').trim(),
    };
    create.mutate(body, {
      onSuccess: () => { toast('success', 'Membership created.'); reset(); onClose(); },
      onError: (err) => toast('error', err.message),
    });
  });
  return (
    <Modal open={open} onClose={onClose} title="New membership">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <SelectInput
          label="Member" required
          {...register('member_id', { required: 'Pick a member.' })}
          options={[
            { value: '', label: 'Select member…' },
            ...((members.data?.items ?? []).map((m) => ({ value: m.id, label: m.display_name || m.id }))),
          ]}
          hint="Register the member first, then enrol."
        />
        <TextInput label="Plan ID (optional)" placeholder="Leave empty for custom pricing" {...register('plan_id')} />
        <div className="grid gap-4 sm:grid-cols-2">
          <TextInput label="Start date" type="date" {...register('start_date')} />
          <TextInput label="End date" type="date" {...register('end_date')} />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextInput label="Price" inputMode="decimal" placeholder="0.00" {...register('price')} />
          <TextInput label="Discount" inputMode="decimal" placeholder="0.00" {...register('discount')} />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={create.isPending}>Create</Button>
        </div>
      </form>
    </Modal>
  );
}

function RenewDialog({ target, onClose }: { target: Membership | null; onClose: () => void }): JSX.Element {
  const toast = useToast();
  const renew = useRenewMembership(target?.id ?? '');
  const confirm = (): void => {
    if (!target) return;
    renew.mutate(
      {},
      {
        onSuccess: () => { toast('success', 'Membership renewed — a new enrolment was created.'); onClose(); },
        onError: (err) => toast('error', err.message),
      },
    );
  };
  return (
    <ConfirmDialog
      open={Boolean(target)}
      onClose={onClose}
      onConfirm={confirm}
      title="Renew membership"
      message={`Create a new enrolment continuing from ${target ? formatDate(target.end_date) : ''}? History is preserved; nothing is deleted.`}
      confirmLabel="Renew"
      pending={renew.isPending}
    />
  );
}

function CancelDialog({ target, onClose }: { target: Membership | null; onClose: () => void }): JSX.Element {
  const toast = useToast();
  const cancel = useSetMembershipStatus(target?.id ?? '');
  const { register, handleSubmit, reset } = useForm({ defaultValues: { cancel_reason: '' } });
  const onSubmit = handleSubmit((values) => {
    if (!target) return;
    cancel.mutate(
      { status: 'cancelled', cancel_reason: values.cancel_reason.trim() },
      {
        onSuccess: () => { toast('success', 'Membership cancelled.'); reset(); onClose(); },
        onError: (err) => toast('error', err.message),
      },
    );
  });
  return (
    <Modal open={Boolean(target)} onClose={onClose} title="Cancel membership">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <p className="text-sm text-slate-600">Cancellation needs a reason (audited). The record is kept, never deleted.</p>
        <TextInput label="Reason" required {...register('cancel_reason', { required: 'A reason is required.' })} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Back</Button>
          <Button variant="danger" type="submit" loading={cancel.isPending}>Cancel membership</Button>
        </div>
      </form>
    </Modal>
  );
}
