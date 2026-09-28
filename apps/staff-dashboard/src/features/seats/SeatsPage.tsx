import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Plus } from 'lucide-react';
import { useSession } from '../../lib/auth';
import {
  useAllocations,
  useAllocateSeat,
  useCreateSeat,
  useFreeSeats,
  useReleaseSeat,
  useSeatAreas,
  useSeatAvailability,
  useSeats,
  useTransferSeat,
} from './hooks';
import { useMembers } from '../members/hooks';
import { useListParams } from '../../lib/list';
import { Badge, Button, Card, PageHeader, StatusBadge } from '../../components/ui/primitives';
import { ConfirmDialog, Modal } from '../../components/ui/overlays';
import { ErrorState, NoResults, TableSkeleton } from '../../components/ui/states';
import { Pagination, SelectInput, TextInput } from '../../components/ui/forms';
import { useToast } from '../../components/ui/Toast';
import type { Seat, SeatAllocation } from '../../types';

const SEAT_STATUSES = ['', 'available', 'reserved', 'occupied', 'blocked', 'maintenance'];
const SEAT_TYPES = ['', 'regular', 'confirmed', 'other'];

/**
 * Seats: server-computed availability, inventory, exclusive allocation
 * with release/transfer. Conflicts surface as 409 (pick another seat).
 */
export function SeatsPage(): JSX.Element {
  const { can } = useSession();
  const manageable = can('seats.manage');
  const { limit, offset, search, setOffset, setSearch } = useListParams();
  const [status, setStatus] = useState('');
  const [seatType, setSeatType] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [allocateOpen, setAllocateOpen] = useState(false);
  const [releaseTarget, setReleaseTarget] = useState<SeatAllocation | null>(null);
  const [transferTarget, setTransferTarget] = useState<SeatAllocation | null>(null);

  const availability = useSeatAvailability();
  const seats = useSeats({ status, seat_type: seatType, search, limit, offset });
  const allocations = useAllocations({ status: 'active', limit: 50, offset: 0 });

  return (
    <div>
      <PageHeader
        title="Seats"
        subtitle="Inventory and exclusive allocation"
        actions={
          manageable ? (
            <>
              <Button size="sm" variant="secondary" onClick={() => setAllocateOpen(true)}>Allocate</Button>
              <Button size="sm" onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4" aria-hidden /> New seat
              </Button>
            </>
          ) : undefined
        }
      />
      {availability.isPending ? (
        <CardsSkeletonInline />
      ) : availability.isError ? (
        <ErrorState message="Could not load availability." onRetry={() => availability.refetch()} />
      ) : (
        <div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Card><p className="text-2xl font-black tabular-nums">{availability.data.total}</p><p className="text-sm text-slate-500">Total seats</p></Card>
          <Card><p className="text-2xl font-black tabular-nums text-emerald-700">{availability.data.available}</p><p className="text-sm text-slate-500">Available</p></Card>
          <Card><p className="text-2xl font-black tabular-nums">{availability.data.allocated_active}</p><p className="text-sm text-slate-500">Allocated</p></Card>
          <Card>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(availability.data.by_status).map(([s, n]) => (
                <span key={s} className="inline-flex items-center gap-1 text-xs"><StatusBadge status={s} /> <strong className="tabular-nums">{n}</strong></span>
              ))}
            </div>
            <p className="mt-1 text-sm text-slate-500">By status</p>
          </Card>
        </div>
      )}

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <TextInput label="Search" placeholder="Seat number…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <SelectInput label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}
            options={SEAT_STATUSES.map((s) => ({ value: s, label: s === '' ? 'All statuses' : s }))} />
          <SelectInput label="Type" value={seatType} onChange={(e) => { setSeatType(e.target.value); setOffset(0); }}
            options={SEAT_TYPES.map((s) => ({ value: s, label: s === '' ? 'All types' : s }))} />
          <div className="flex items-end">
            <Button variant="secondary" size="sm" onClick={() => { setSearch(''); setStatus(''); setSeatType(''); }}>Clear</Button>
          </div>
        </div>
      </Card>

      {seats.isPending ? (
        <Card><TableSkeleton /></Card>
      ) : seats.isError ? (
        <ErrorState message="Could not load seats." onRetry={() => seats.refetch()} />
      ) : seats.data.total === 0 ? (
        <NoResults onClear={() => { setSearch(''); setStatus(''); setSeatType(''); }} />
      ) : (
        <Card className="p-0 sm:p-0">
          <ul className="divide-y divide-slate-100">
            {seats.data.items.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-2 px-5 py-3.5 sm:gap-3">
                <span className="min-w-0 flex-1 basis-40">
                  <span className="block text-sm font-bold text-slate-900">{s.seat_number}</span>
                  <span className="block text-xs text-slate-500">{s.seat_type}</span>
                </span>
                <StatusBadge status={s.status} />
              </li>
            ))}
          </ul>
          <div className="px-5 pb-5">
            <Pagination total={seats.data.total} limit={limit} offset={offset} onChange={setOffset} />
          </div>
        </Card>
      )}

      <Card className="mt-4">
        <h2 className="mb-3 text-base font-bold text-slate-900">Active allocations</h2>
        {allocations.isPending ? (
          <TableSkeleton rows={3} cols={3} />
        ) : allocations.isError ? (
          <p className="py-4 text-center text-sm text-slate-500">Could not load allocations.</p>
        ) : allocations.data.total === 0 ? (
          <p className="py-4 text-center text-sm text-slate-500">No active allocations.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {allocations.data.items.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-2 py-2.5 text-sm sm:gap-3">
                <span className="min-w-0 flex-1 basis-40">
                  <span className="block truncate font-semibold">Seat {a.seat_id.slice(0, 8)}…</span>
                  <span className="block truncate text-xs text-slate-500">member {a.member_id.slice(0, 8)}…</span>
                </span>
                {manageable ? (
                  <span className="flex gap-2">
                    <Button size="sm" variant="secondary" onClick={() => setTransferTarget(a)}>Transfer</Button>
                    <Button size="sm" variant="ghost" onClick={() => setReleaseTarget(a)}>Release</Button>
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <CreateSeatModal open={createOpen} onClose={() => setCreateOpen(false)} />
      <AllocateModal open={allocateOpen} onClose={() => setAllocateOpen(false)} />
      <ReleaseDialog target={releaseTarget} onClose={() => setReleaseTarget(null)} />
      <TransferModal target={transferTarget} onClose={() => setTransferTarget(null)} />
    </div>
  );
}

function CardsSkeletonInline(): JSX.Element {
  return (
    <div role="status" aria-label="Loading" className="mb-4 grid animate-pulse gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="h-24 rounded-2xl bg-slate-200" />
      ))}
    </div>
  );
}

function CreateSeatModal({ open, onClose }: { open: boolean; onClose: () => void }): JSX.Element {
  const toast = useToast();
  const create = useCreateSeat();
  const areas = useSeatAreas();
  const { register, handleSubmit, reset } = useForm({
    defaultValues: { seat_number: '', area_id: '', seat_type: 'regular', notes: '' },
  });
  const onSubmit = handleSubmit((values) => {
    create.mutate(
      {
        seat_number: values.seat_number.trim(),
        area_id: values.area_id || null,
        seat_type: values.seat_type,
        notes: values.notes.trim(),
      },
      {
        onSuccess: () => { toast('success', 'Seat created.'); reset(); onClose(); },
        onError: (err) => toast('error', err.message),
      },
    );
  });
  return (
    <Modal open={open} onClose={onClose} title="New seat">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <TextInput label="Seat number" required placeholder="R-01" {...register('seat_number', { required: 'Seat number is required.' })} />
        <div className="grid gap-4 sm:grid-cols-2">
          <SelectInput label="Area" {...register('area_id')}
            options={[{ value: '', label: 'No area…' }, ...((areas.data?.items ?? []).map((a) => ({ value: a.id, label: a.name })))]}
          />
          <SelectInput label="Type" {...register('seat_type')}
            options={SEAT_TYPES.filter(Boolean).map((s) => ({ value: s, label: s }))} />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={create.isPending}>Create</Button>
        </div>
      </form>
    </Modal>
  );
}

function AllocateModal({ open, onClose }: { open: boolean; onClose: () => void }): JSX.Element {
  const toast = useToast();
  const allocate = useAllocateSeat();
  const free = useFreeSeats();
  const members = useMembers({ limit: 100, offset: 0 });
  const { register, handleSubmit, reset } = useForm({ defaultValues: { seat_id: '', member_id: '', notes: '' } });
  const onSubmit = handleSubmit((values) => {
    allocate.mutate(
      { seat_id: values.seat_id, member_id: values.member_id, notes: values.notes.trim() },
      {
        onSuccess: () => { toast('success', 'Seat allocated.'); reset(); onClose(); },
        onError: (err) => toast('error', err.message),
      },
    );
  });
  return (
    <Modal open={open} onClose={onClose} title="Allocate seat">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <SelectInput label="Free seat" required {...register('seat_id', { required: 'Pick a seat.' })}
          options={[{ value: '', label: free.isPending ? 'Loading…' : 'Select seat…' }, ...((free.data?.items ?? []).map((s: Seat) => ({ value: s.id, label: `${s.seat_number} (${s.seat_type})` })))]}
          hint="Only currently-free seats are listed (server-computed)."
        />
        <SelectInput label="Member" required {...register('member_id', { required: 'Pick a member.' })}
          options={[{ value: '', label: 'Select member…' }, ...((members.data?.items ?? []).map((m) => ({ value: m.id, label: m.display_name || m.id })))]}
        />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={allocate.isPending}>Allocate</Button>
        </div>
      </form>
    </Modal>
  );
}

function ReleaseDialog({ target, onClose }: { target: SeatAllocation | null; onClose: () => void }): JSX.Element {
  const toast = useToast();
  const release = useReleaseSeat();
  const confirm = (): void => {
    if (!target) return;
    release.mutate(
      { id: target.id },
      {
        onSuccess: () => { toast('success', 'Seat released. History preserved.'); onClose(); },
        onError: (err) => toast('error', err.message),
      },
    );
  };
  return (
    <ConfirmDialog
      open={Boolean(target)}
      onClose={onClose}
      onConfirm={confirm}
      title="Release seat"
      message="Free this seat? The allocation stays in history; the member keeps their membership."
      confirmLabel="Release"
      pending={release.isPending}
    />
  );
}

function TransferModal({ target, onClose }: { target: SeatAllocation | null; onClose: () => void }): JSX.Element {
  const toast = useToast();
  const transfer = useTransferSeat();
  const members = useMembers({ limit: 100, offset: 0 });
  const { register, handleSubmit, reset } = useForm({ defaultValues: { to_member_id: '' } });
  const onSubmit = handleSubmit((values) => {
    if (!target) return;
    transfer.mutate(
      { id: target.id, to_member_id: values.to_member_id },
      {
        onSuccess: () => { toast('success', 'Seat transferred.'); reset(); onClose(); },
        onError: (err) => toast('error', err.message),
      },
    );
  });
  return (
    <Modal open={Boolean(target)} onClose={onClose} title="Transfer seat">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <SelectInput label="Move to member" required {...register('to_member_id', { required: 'Pick a member.' })}
          options={[{ value: '', label: 'Select member…' }, ...((members.data?.items ?? []).filter((m) => m.id !== target?.member_id).map((m) => ({ value: m.id, label: m.display_name || m.id })))]}
        />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={transfer.isPending}>Transfer</Button>
        </div>
      </form>
    </Modal>
  );
}

export function SeatBadge({ status }: { status: string }): JSX.Element {
  const tone = status === 'available' ? 'green' : status === 'occupied' ? 'blue' : status === 'maintenance' ? 'rose' : 'slate';
  return <Badge tone={tone}>{status}</Badge>;
}
