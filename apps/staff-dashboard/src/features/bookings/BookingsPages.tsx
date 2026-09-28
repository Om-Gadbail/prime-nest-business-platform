import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { Plus } from 'lucide-react';
import { useSession } from '../../lib/auth';
import { useBooking, useBookingTransition, useBookings, useCreateBooking } from './hooks';
import { useListParams, formatDateTime } from '../../lib/list';
import { Button, Card, PageHeader, StatusBadge } from '../../components/ui/primitives';
import { Modal } from '../../components/ui/overlays';
import { ErrorState, NoResults, TableSkeleton } from '../../components/ui/states';
import { Pagination, SelectInput, TextArea, TextInput } from '../../components/ui/forms';
import { useToast } from '../../components/ui/Toast';

const STATUSES = ['', 'requested', 'confirmed', 'completed', 'cancelled', 'no_show'];
const TYPES = ['', 'trial', 'visit', 'consultation', 'enquiry', 'other'];

/** Bookings / visit requests: list, filters, create, detail, transitions. */
export function BookingsPage(): JSX.Element {
  const { can } = useSession();
  const { limit, offset, setOffset } = useListParams();
  const [status, setStatus] = useState('');
  const [bookingType, setBookingType] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const query = useBookings({ status, booking_type: bookingType, limit, offset });

  return (
    <div>
      <PageHeader
        title="Bookings"
        subtitle="Visit and trial requests — requested until staff confirm"
        actions={
          can('bookings.create') ? (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden /> New booking
            </Button>
          ) : undefined
        }
      />
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <SelectInput
            label="Status" value={status}
            onChange={(e) => { setStatus(e.target.value); setOffset(0); }}
            options={STATUSES.map((s) => ({ value: s, label: s === '' ? 'All statuses' : s.replace(/_/g, ' ') }))}
          />
          <SelectInput
            label="Type" value={bookingType}
            onChange={(e) => { setBookingType(e.target.value); setOffset(0); }}
            options={TYPES.map((s) => ({ value: s, label: s === '' ? 'All types' : s }))}
          />
          <div className="flex items-end">
            <Button variant="secondary" size="sm" onClick={() => { setStatus(''); setBookingType(''); }}>Clear</Button>
          </div>
        </div>
      </Card>
      {query.isPending ? (
        <Card><TableSkeleton /></Card>
      ) : query.isError ? (
        <ErrorState message={query.error instanceof Error ? query.error.message : 'Could not load bookings.'} onRetry={() => query.refetch()} />
      ) : query.data.total === 0 ? (
        <NoResults />
      ) : (
        <Card className="p-0 sm:p-0">
          <ul className="divide-y divide-slate-100">
            {query.data.items.map((b) => (
              <li key={b.id}>
                <Link to={`/bookings/${b.id}`} className="flex flex-wrap items-center gap-2 px-5 py-3.5 hover:bg-slate-50 sm:gap-3">
                  <span className="min-w-0 flex-1 basis-48">
                    <span className="block truncate text-sm font-semibold text-slate-900">{b.title || `${b.booking_type} request`}</span>
                    <span className="block truncate text-xs text-slate-500">
                      {formatDateTime(b.requested_start_at)} · {b.booking_type}
                    </span>
                  </span>
                  <StatusBadge status={b.status} />
                  <span className="w-full text-xs text-slate-400 sm:w-auto">{formatDateTime(b.created_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
          <div className="px-5 pb-5">
            <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />
          </div>
        </Card>
      )}
      <CreateBookingModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}

export function BookingDetailPage(): JSX.Element {
  const { id = '' } = useParams();
  const { can } = useSession();
  const navigate = useNavigate();
  const toast = useToast();
  const booking = useBooking(id);
  const transition = useBookingTransition(id);
  const [cancelOpen, setCancelOpen] = useState(false);

  if (booking.isPending) return <Card><TableSkeleton /></Card>;
  if (booking.isError) {
    return <ErrorState title="Booking not found" message={booking.error instanceof Error ? booking.error.message : undefined} onRetry={() => booking.refetch()} />;
  }
  const data = booking.data;
  const act = (action: 'confirm' | 'complete' | 'no-show' | 'reopen' | 'cancel', reason?: string): void => {
    transition.mutate(
      { action, cancellation_reason: reason },
      {
        onSuccess: (b) => toast('success', `Booking ${b.status.replace(/_/g, ' ')}.`),
        onError: (e) => toast('error', e.message),
      },
    );
  };

  return (
    <div>
      <PageHeader
        title={data.title || `${data.booking_type} request`}
        subtitle={`Requested ${formatDateTime(data.created_at)}`}
        actions={<Button variant="secondary" size="sm" onClick={() => navigate('/bookings')}>Back to bookings</Button>}
      />
      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={data.status} />
          </div>
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
            <Read label="Type" value={data.booking_type} />
            <Read label="Source" value={data.source} />
            <Read label="Requested start" value={formatDateTime(data.requested_start_at)} />
            <Read label="Requested end" value={formatDateTime(data.requested_end_at)} />
            {data.cancellation_reason ? <Read label="Cancellation reason" value={data.cancellation_reason} /> : null}
          </dl>
          {data.notes ? <p className="mt-4 rounded-xl bg-slate-50 p-3.5 text-sm text-slate-700 ring-1 ring-slate-200/60">{data.notes}</p> : null}
          {can('bookings.update') ? (
            <div className="mt-4 flex flex-wrap gap-2">
              {data.status === 'requested' ? <Button size="sm" onClick={() => act('confirm')} loading={transition.isPending}>Confirm</Button> : null}
              {data.status === 'confirmed' ? <Button size="sm" onClick={() => act('complete')} loading={transition.isPending}>Complete</Button> : null}
              {['requested', 'confirmed'].includes(data.status) ? (
                <>
                  <Button size="sm" variant="secondary" onClick={() => act('no-show')} loading={transition.isPending}>Mark no-show</Button>
                  <Button size="sm" variant="secondary" onClick={() => setCancelOpen(true)}>Cancel…</Button>
                </>
              ) : null}
              {['cancelled', 'no_show'].includes(data.status) ? (
                <Button size="sm" variant="secondary" onClick={() => act('reopen')} loading={transition.isPending}>
                  Re-open to requested
                </Button>
              ) : null}
            </div>
          ) : null}
        </Card>
        <Card>
          <h2 className="mb-2 text-base font-bold text-slate-900">Honesty rule</h2>
          <p className="text-sm text-slate-600">
            A booking is only confirmed when staff confirm it here. Public forms always create
            <span className="font-semibold"> requested </span> rows.
          </p>
        </Card>
      </div>
      <CancelModal open={cancelOpen} onClose={() => setCancelOpen(false)} onConfirm={(reason) => act('cancel', reason)} pending={transition.isPending} />
    </div>
  );
}

function Read({ label, value }: { label: string; value?: string | null }): JSX.Element {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="text-sm font-medium text-slate-800">{value && value.trim() ? value : '—'}</dd>
    </div>
  );
}

function CancelModal({ open, onClose, onConfirm, pending }: { open: boolean; onClose: () => void; onConfirm: (reason: string) => void; pending: boolean }): JSX.Element {
  const { register, handleSubmit } = useForm<{ cancellation_reason: string }>({ defaultValues: { cancellation_reason: '' } });
  return (
    <Modal open={open} onClose={onClose} title="Cancel booking">
      <form onSubmit={handleSubmit((v) => { onConfirm(v.cancellation_reason); onClose(); })} className="space-y-4">
        <TextArea label="Cancellation reason" required hint="Required — recorded in the audit trail." {...register('cancellation_reason', { required: true })} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Back</Button>
          <Button type="submit" variant="danger" loading={pending}>Cancel booking</Button>
        </div>
      </form>
    </Modal>
  );
}

function CreateBookingModal({ open, onClose }: { open: boolean; onClose: () => void }): JSX.Element {
  const toast = useToast();
  const create = useCreateBooking();
  const { register, handleSubmit, reset } = useForm<{ title: string; booking_type: string; requested_start_at: string; notes: string }>({
    defaultValues: { title: '', booking_type: 'enquiry', requested_start_at: '', notes: '' },
  });
  const onSubmit = handleSubmit((v) => {
    create.mutate(
      {
        title: v.title,
        booking_type: v.booking_type,
        requested_start_at: v.requested_start_at ? new Date(v.requested_start_at).toISOString() : null,
        notes: v.notes,
      },
      {
        onSuccess: () => { toast('success', 'Booking request created.'); reset(); onClose(); },
        onError: (e) => toast('error', e.message),
      },
    );
  });
  return (
    <Modal open={open} onClose={onClose} title="New booking request">
      <form onSubmit={onSubmit} className="space-y-4">
        <TextInput label="Title" required {...register('title', { required: 'Title is required.' })} />
        <SelectInput label="Type" {...register('booking_type')} options={TYPES.filter(Boolean).map((t) => ({ value: t, label: t }))} />
        <TextInput label="Requested start" type="datetime-local" {...register('requested_start_at')} />
        <TextArea label="Notes" {...register('notes')} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={create.isPending}>Create request</Button>
        </div>
      </form>
    </Modal>
  );
}
