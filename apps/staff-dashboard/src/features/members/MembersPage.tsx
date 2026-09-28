import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link } from 'react-router-dom';
import { Plus } from 'lucide-react';
import { useSession } from '../../lib/auth';
import { useCreateMember, useMembers } from './hooks';
import { useListParams } from '../../lib/list';
import { Button, Card, PageHeader, StatusBadge } from '../../components/ui/primitives';
import { Modal } from '../../components/ui/overlays';
import { ErrorState, NoResults, TableSkeleton } from '../../components/ui/states';
import { Pagination, SelectInput, TextInput } from '../../components/ui/forms';
import { useToast } from '../../components/ui/Toast';
import { formatDateTime } from '../../lib/list';

const STATUSES = ['', 'active', 'inactive', 'archived'];

/** Members: list, search, status filter, register. */
export function MembersPage(): JSX.Element {
  const { can } = useSession();
  const { limit, offset, search, setOffset, setSearch } = useListParams();
  const [status, setStatus] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const query = useMembers({ status, search, limit, offset });

  const clearFilters = (): void => {
    setSearch('');
    setStatus('');
  };

  return (
    <div>
      <PageHeader
        title="Members"
        subtitle="Operational member profiles"
        actions={
          can('members.create') ? (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden /> New member
            </Button>
          ) : undefined
        }
      />
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <TextInput label="Search" placeholder="Name, phone, email…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <SelectInput
            label="Status"
            value={status}
            onChange={(e) => { setStatus(e.target.value); setOffset(0); }}
            options={STATUSES.map((s) => ({ value: s, label: s === '' ? 'All statuses' : s }))}
          />
          <div className="flex items-end">
            <Button variant="secondary" size="sm" onClick={clearFilters}>Clear</Button>
          </div>
        </div>
      </Card>
      {query.isPending ? (
        <Card><TableSkeleton /></Card>
      ) : query.isError ? (
        <ErrorState message={query.error instanceof Error ? query.error.message : 'Could not load members.'} onRetry={() => query.refetch()} />
      ) : query.data.total === 0 ? (
        <NoResults onClear={clearFilters} />
      ) : (
        <Card className="p-0 sm:p-0">
          <ul className="divide-y divide-slate-100">
            {query.data.items.map((m) => (
              <li key={m.id}>
                <Link to={`/members/${m.id}`} className="flex flex-wrap items-center gap-2 px-5 py-3.5 transition hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-slate-900 sm:gap-3">
                  <span className="min-w-0 flex-1 basis-48">
                    <span className="block truncate text-sm font-semibold text-slate-900">{m.display_name || 'Unnamed member'}</span>
                    <span className="block truncate text-xs text-slate-500">
                      {[m.phone, m.email].filter(Boolean).join(' · ') || 'No contact details'}
                    </span>
                  </span>
                  <StatusBadge status={m.status} />
                  <span className="w-full text-xs text-slate-400 sm:w-auto">{formatDateTime(m.created_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
          <div className="px-5 pb-5">
            <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />
          </div>
        </Card>
      )}
      <CreateMemberModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}

interface CreateValues {
  display_name: string;
  phone: string;
  email: string;
  emergency_contact_name: string;
  emergency_contact_phone: string;
  seat_preference: string;
  notes: string;
}

function CreateMemberModal({ open, onClose }: { open: boolean; onClose: () => void }): JSX.Element {
  const toast = useToast();
  const create = useCreateMember();
  const { register, handleSubmit, reset } = useForm<CreateValues>({
    defaultValues: { display_name: '', phone: '', email: '', emergency_contact_name: '', emergency_contact_phone: '', seat_preference: '', notes: '' },
  });
  const onSubmit = handleSubmit((values) => {
    const body: Record<string, unknown> = {
      display_name: values.display_name.trim(),
      phone: values.phone.trim() || null,
      email: values.email.trim() || null,
      emergency_contact_name: values.emergency_contact_name.trim(),
      emergency_contact_phone: values.emergency_contact_phone.trim() || null,
      seat_preference: values.seat_preference.trim(),
      notes: values.notes.trim(),
    };
    create.mutate(body, {
      onSuccess: () => {
        toast('success', 'Member registered.');
        reset();
        onClose();
      },
      onError: (err) => toast('error', err.message),
    });
  });
  return (
    <Modal open={open} onClose={onClose} title="New member">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <TextInput label="Name" required {...register('display_name', { required: 'Name, phone, or email is required.' })} />
        <div className="grid gap-4 sm:grid-cols-2">
          <TextInput label="Phone" placeholder="+91…" {...register('phone')} />
          <TextInput label="Email" type="email" {...register('email')} />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextInput label="Emergency contact" {...register('emergency_contact_name')} />
          <TextInput label="Emergency phone" {...register('emergency_contact_phone')} />
        </div>
        <TextInput label="Seat preference" placeholder="Window, ground floor…" {...register('seat_preference')} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={create.isPending}>Register</Button>
        </div>
      </form>
    </Modal>
  );
}
