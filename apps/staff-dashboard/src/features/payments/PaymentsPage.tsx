import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Plus } from 'lucide-react';
import { useSession } from '../../lib/auth';
import { useCreatePayment, usePayments, useRefundPayment, useSetPaymentStatus } from './hooks';
import { useMembers } from '../members/hooks';
import { useListParams } from '../../lib/list';
import { Button, Card, PageHeader, StatusBadge } from '../../components/ui/primitives';
import { ConfirmDialog, Modal } from '../../components/ui/overlays';
import { ErrorState, NoResults, TableSkeleton } from '../../components/ui/states';
import { Pagination, SelectInput, TextArea, TextInput } from '../../components/ui/forms';
import { useToast } from '../../components/ui/Toast';
import { formatDateTime, formatMoney } from '../../lib/list';
import type { Payment } from '../../types';

const STATUSES = ['', 'pending', 'paid', 'failed', 'cancelled', 'refunded', 'partially_paid', 'overdue'];
const METHODS = ['', 'cash', 'upi', 'bank_transfer', 'card', 'online', 'manual'];

/** Payments: fee records, staff-confirmed settlement, gated refunds. */
export function PaymentsPage(): JSX.Element {
  const { can } = useSession();
  const { limit, offset, setOffset } = useListParams();
  const [status, setStatus] = useState('');
  const [method, setMethod] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [payTarget, setPayTarget] = useState<Payment | null>(null);
  const [refundTarget, setRefundTarget] = useState<Payment | null>(null);
  const query = usePayments({ status, method, limit, offset });

  return (
    <div>
      <PageHeader
        title="Payments"
        subtitle="Provider-neutral fee records"
        actions={
          can('payments.create') ? (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden /> Record payment
            </Button>
          ) : undefined
        }
      />
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <SelectInput label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}
            options={STATUSES.map((s) => ({ value: s, label: s === '' ? 'All statuses' : s.replace(/_/g, ' ') }))} />
          <SelectInput label="Method" value={method} onChange={(e) => { setMethod(e.target.value); setOffset(0); }}
            options={METHODS.map((s) => ({ value: s, label: s === '' ? 'All methods' : s.replace(/_/g, ' ') }))} />
          <div className="flex items-end">
            <Button variant="secondary" size="sm" onClick={() => { setStatus(''); setMethod(''); }}>Clear</Button>
          </div>
        </div>
      </Card>
      {query.isPending ? (
        <Card><TableSkeleton /></Card>
      ) : query.isError ? (
        <ErrorState message={query.error instanceof Error ? query.error.message : 'Could not load payments.'} onRetry={() => query.refetch()} />
      ) : query.data.total === 0 ? (
        <NoResults onClear={() => { setStatus(''); setMethod(''); }} />
      ) : (
        <Card className="p-0 sm:p-0">
          <ul className="divide-y divide-slate-100">
            {query.data.items.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-2 px-5 py-3.5 sm:gap-3">
                <span className="min-w-0 flex-1 basis-40">
                  <span className="block text-sm font-bold tabular-nums text-slate-900">{formatMoney(p.amount, p.currency)}</span>
                  <span className="block truncate text-xs text-slate-500">{p.method.replace(/_/g, ' ')} · {formatDateTime(p.created_at)}</span>
                </span>
                <StatusBadge status={p.status} />
                <span className="flex w-full gap-2 sm:w-auto">
                  {can('payments.update') && (p.status === 'pending' || p.status === 'partially_paid' || p.status === 'overdue') ? (
                    <Button size="sm" variant="secondary" onClick={() => setPayTarget(p)}>Mark paid</Button>
                  ) : null}
                  {can('payments.refund') && p.status === 'paid' ? (
                    <Button size="sm" variant="ghost" onClick={() => setRefundTarget(p)}>Refund</Button>
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
      <CreatePaymentModal open={createOpen} onClose={() => setCreateOpen(false)} />
      <MarkPaidDialog target={payTarget} onClose={() => setPayTarget(null)} />
      <RefundDialog target={refundTarget} onClose={() => setRefundTarget(null)} />
    </div>
  );
}

function CreatePaymentModal({ open, onClose }: { open: boolean; onClose: () => void }): JSX.Element {
  const toast = useToast();
  const create = useCreatePayment();
  const members = useMembers({ limit: 100, offset: 0 });
  const { register, handleSubmit, reset } = useForm({
    defaultValues: { amount: '', method: 'upi', member_id: '', membership_id: '', provider_ref: '', notes: '' },
  });
  const onSubmit = handleSubmit((values) => {
    create.mutate(
      {
        amount: values.amount,
        method: values.method,
        member_id: values.member_id || null,
        membership_id: values.membership_id || null,
        provider_ref: values.provider_ref.trim(),
        notes: values.notes.trim(),
      },
      {
        onSuccess: () => { toast('success', 'Payment recorded as pending.'); reset(); onClose(); },
        onError: (err) => toast('error', err.message),
      },
    );
  });
  return (
    <Modal open={open} onClose={onClose} title="Record payment">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextInput label="Amount" required inputMode="decimal" placeholder="0.00" {...register('amount', { required: 'Amount is required.' })} />
          <SelectInput label="Method" {...register('method')}
            options={METHODS.filter(Boolean).map((m) => ({ value: m, label: m.replace(/_/g, ' ') }))} />
        </div>
        <SelectInput label="Member (optional)" {...register('member_id')}
          options={[{ value: '', label: 'No member…' }, ...((members.data?.items ?? []).map((m) => ({ value: m.id, label: m.display_name || m.id })))]}
        />
        <TextInput label="Membership ID (optional)" {...register('membership_id')} />
        <TextInput label="Reference (UTR / receipt)" {...register('provider_ref')} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={create.isPending}>Record</Button>
        </div>
      </form>
    </Modal>
  );
}

function MarkPaidDialog({ target, onClose }: { target: Payment | null; onClose: () => void }): JSX.Element {
  const toast = useToast();
  const settle = useSetPaymentStatus(target?.id ?? '');
  const confirm = (): void => {
    if (!target) return;
    settle.mutate(
      { status: 'paid' },
      {
        onSuccess: () => { toast('success', 'Payment marked as paid.'); onClose(); },
        onError: (err) => toast('error', err.message),
      },
    );
  };
  return (
    <ConfirmDialog
      open={Boolean(target)}
      onClose={onClose}
      onConfirm={confirm}
      title="Confirm money received"
      message={`Mark ${target ? formatMoney(target.amount, target.currency) : ''} as PAID? Only confirm money you have actually received.`}
      confirmLabel="Mark paid"
      pending={settle.isPending}
    />
  );
}

function RefundDialog({ target, onClose }: { target: Payment | null; onClose: () => void }): JSX.Element {
  const toast = useToast();
  const refund = useRefundPayment(target?.id ?? '');
  const { register, handleSubmit, reset } = useForm({ defaultValues: { reason: '' } });
  const onSubmit = handleSubmit((values) => {
    if (!target) return;
    refund.mutate(
      { reason: values.reason.trim() },
      {
        onSuccess: () => { toast('success', 'Payment refunded.'); reset(); onClose(); },
        onError: (err) => toast('error', err.message),
      },
    );
  });
  return (
    <Modal open={Boolean(target)} onClose={onClose} title="Refund payment">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <p className="text-sm text-slate-600">Refunds are audited and final. Only refund money actually returned.</p>
        <TextArea label="Reason" required {...register('reason', { required: 'A reason is required.', minLength: { value: 5, message: 'Give a clear reason.' } })} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Back</Button>
          <Button variant="danger" type="submit" loading={refund.isPending}>Refund</Button>
        </div>
      </form>
    </Modal>
  );
}
