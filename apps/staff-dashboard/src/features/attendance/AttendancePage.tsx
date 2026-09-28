import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Plus } from 'lucide-react';
import { useSession } from '../../lib/auth';
import { useAttendance, useCheckIn, useCheckOut } from './hooks';
import { useMembers } from '../members/hooks';
import { useListParams } from '../../lib/list';
import { Button, Card, PageHeader } from '../../components/ui/primitives';
import { Modal } from '../../components/ui/overlays';
import { ErrorState, NoResults, TableSkeleton } from '../../components/ui/states';
import { Pagination, SelectInput, TextInput } from '../../components/ui/forms';
import { useToast } from '../../components/ui/Toast';
import { formatDate, formatDateTime } from '../../lib/list';

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Attendance: today's register, member history, manual check-in/out. */
export function AttendancePage(): JSX.Element {
  const { can } = useSession();
  const { limit, offset, setOffset } = useListParams();
  const [day, setDay] = useState(todayISO());
  const [memberFilter, setMemberFilter] = useState('');
  const [checkInOpen, setCheckInOpen] = useState(false);
  const query = useAttendance({ day, member_id: memberFilter || undefined, limit, offset });
  const checkOut = useCheckOut();
  const toast = useToast();

  return (
    <div>
      <PageHeader
        title="Attendance"
        subtitle={day === todayISO() ? "Who is here today" : `Register for ${day}`}
        actions={
          can('attendance.create') ? (
            <Button size="sm" onClick={() => setCheckInOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden /> Check in
            </Button>
          ) : undefined
        }
      />
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <TextInput label="Day" type="date" value={day} onChange={(e) => { setDay(e.target.value); setOffset(0); }} />
          <TextInput label="Member ID" placeholder="Filter by member…" value={memberFilter} onChange={(e) => { setMemberFilter(e.target.value); setOffset(0); }} />
          <div className="flex items-end">
            <Button variant="secondary" size="sm" onClick={() => { setDay(todayISO()); setMemberFilter(''); }}>Today</Button>
          </div>
        </div>
      </Card>
      {query.isPending ? (
        <Card><TableSkeleton /></Card>
      ) : query.isError ? (
        <ErrorState message={query.error instanceof Error ? query.error.message : 'Could not load attendance.'} onRetry={() => query.refetch()} />
      ) : query.data.total === 0 ? (
        <NoResults onClear={() => { setDay(todayISO()); setMemberFilter(''); }} />
      ) : (
        <Card className="p-0 sm:p-0">
          <ul className="divide-y divide-slate-100">
            {query.data.items.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-2 px-5 py-3.5 sm:gap-3">
                <span className="min-w-0 flex-1 basis-48">
                  <span className="block truncate text-sm font-semibold text-slate-900">{formatDate(a.attendance_date)}</span>
                  <span className="block truncate text-xs text-slate-500">
                    in {formatDateTime(a.checked_in_at)}{a.checked_out_at ? ` · out ${formatDateTime(a.checked_out_at)}` : ' · still here'}
                  </span>
                </span>
                {!a.checked_out_at && can('attendance.create') ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={checkOut.isPending}
                    onClick={() => checkOut.mutate(
                      { id: a.id },
                      { onSuccess: () => toast('success', 'Checked out.'), onError: (err) => toast('error', err.message) },
                    )}
                  >
                    Check out
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
          <div className="px-5 pb-5">
            <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />
          </div>
        </Card>
      )}
      <CheckInModal open={checkInOpen} onClose={() => setCheckInOpen(false)} />
    </div>
  );
}

function CheckInModal({ open, onClose }: { open: boolean; onClose: () => void }): JSX.Element {
  const toast = useToast();
  const checkIn = useCheckIn();
  const members = useMembers({ limit: 100, offset: 0 });
  const { register, handleSubmit, reset } = useForm({ defaultValues: { member_id: '', source: 'manual' } });
  const onSubmit = handleSubmit((values) => {
    checkIn.mutate(
      { member_id: values.member_id, source: values.source },
      {
        onSuccess: () => { toast('success', 'Checked in.'); reset(); onClose(); },
        onError: (err) => toast('error', err.message),
      },
    );
  });
  return (
    <Modal open={open} onClose={onClose} title="Check in">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <SelectInput label="Member" required {...register('member_id', { required: 'Pick a member.' })}
          options={[{ value: '', label: 'Select member…' }, ...((members.data?.items ?? []).map((m) => ({ value: m.id, label: m.display_name || m.id })))]}
        />
        <SelectInput label="Source" {...register('source')}
          options={['manual', 'qr', 'kiosk', 'mobile', 'rfid'].map((s) => ({ value: s, label: s }))} />
        <p className="text-xs text-slate-500">Repeat check-ins on the same day return the existing record — no duplicates.</p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={checkIn.isPending}>Check in</Button>
        </div>
      </form>
    </Modal>
  );
}
