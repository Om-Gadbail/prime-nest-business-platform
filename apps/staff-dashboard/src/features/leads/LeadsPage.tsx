import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, useSearchParams } from 'react-router-dom';
import { Plus } from 'lucide-react';
import { useSession } from '../../lib/auth';
import { useCreateLead, useLeads } from './hooks';
import { useListParams } from '../../lib/list';
import { Badge, Button, Card, PageHeader, StatusBadge } from '../../components/ui/primitives';
import { Modal } from '../../components/ui/overlays';
import { ErrorState, NoResults, TableSkeleton } from '../../components/ui/states';
import { Pagination, SelectInput, TextArea, TextInput } from '../../components/ui/forms';
import { useToast } from '../../components/ui/Toast';
import { formatDateTime } from '../../lib/list';

const STATUSES = ['', 'new', 'contacted', 'qualified', 'booked', 'converted', 'lost', 'spam'];
const SOURCES = ['', 'website', 'whatsapp', 'phone', 'walk_in', 'referral', 'instagram', 'facebook', 'google', 'other'];

/** Leads: list, search, filters, status/source, create. */
export function LeadsPage(): JSX.Element {
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const { limit, offset, search, setOffset, setSearch } = useListParams();
  const [status, setStatus] = useState(() => params.get('status') ?? '');
  const [source, setSource] = useState('');
  const [createOpen, setCreateOpen] = useState(() => params.get('new') === '1');

  const query = useLeads({ status, source, search, limit, offset });

  const clearFilters = (): void => {
    setSearch('');
    setStatus('');
    setSource('');
    setParams({});
  };

  return (
    <div>
      <PageHeader
        title="Leads"
        subtitle="Enquiries routed to this business"
        actions={
          can('leads.create') ? (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden /> New lead
            </Button>
          ) : undefined
        }
      />

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <TextInput
            label="Search"
            placeholder="Name, phone, email, interest…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <SelectInput
            label="Status"
            value={status}
            onChange={(e) => { setStatus(e.target.value); setOffset(0); }}
            options={STATUSES.map((s) => ({ value: s, label: s === '' ? 'All statuses' : s }))}
          />
          <SelectInput
            label="Source"
            value={source}
            onChange={(e) => { setSource(e.target.value); setOffset(0); }}
            options={SOURCES.map((s) => ({ value: s, label: s === '' ? 'All sources' : s }))}
          />
          <div className="flex items-end">
            <Button variant="secondary" size="sm" onClick={clearFilters}>Clear</Button>
          </div>
        </div>
      </Card>

      {query.isPending ? (
        <Card><TableSkeleton /></Card>
      ) : query.isError ? (
        <ErrorState
          message={query.error instanceof Error ? query.error.message : 'Could not load leads.'}
          onRetry={() => query.refetch()}
        />
      ) : query.data.total === 0 ? (
        <NoResults onClear={clearFilters} />
      ) : (
        <Card className="p-0 sm:p-0">
          <ul className="divide-y divide-slate-100">
            {query.data.items.map((lead) => (
              <li key={lead.id}>
                <Link
                  to={`/leads/${lead.id}`}
                  className="flex flex-wrap items-center gap-2 px-5 py-3.5 transition hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-slate-900 sm:gap-3"
                >
                  <span className="min-w-0 flex-1 basis-48">
                    <span className="block truncate text-sm font-semibold text-slate-900">
                      {lead.display_name || 'Unnamed lead'}
                    </span>
                    <span className="block truncate text-xs text-slate-500">
                      {[lead.phone, lead.email].filter(Boolean).join(' · ') || 'No contact details'}
                    </span>
                  </span>
                  <span className="hidden text-xs text-slate-500 md:block">
                    {lead.service_interest || lead.source_detail || lead.source}
                  </span>
                  <StatusBadge status={lead.status} />
                  {lead.follow_up_at ? <Badge tone="amber">follow-up</Badge> : null}
                  <span className="w-full text-xs text-slate-400 sm:w-auto">{formatDateTime(lead.created_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
          <div className="px-5 pb-5">
            <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />
          </div>
        </Card>
      )}

      <CreateLeadModal open={createOpen} onClose={() => { setCreateOpen(false); setParams({}); }} />
    </div>
  );
}

interface CreateValues {
  display_name: string;
  phone: string;
  email: string;
  service_interest: string;
  message: string;
}

function CreateLeadModal({ open, onClose }: { open: boolean; onClose: () => void }): JSX.Element {
  const toast = useToast();
  const create = useCreateLead();
  const { register, handleSubmit, reset, formState: { errors } } = useForm<CreateValues>({
    defaultValues: { display_name: '', phone: '', email: '', service_interest: '', message: '' },
  });

  const onSubmit = handleSubmit((values) => {
    create.mutate(
      {
        display_name: values.display_name.trim(),
        phone: values.phone.trim() || null,
        email: values.email.trim() || null,
        service_interest: values.service_interest.trim(),
        message: values.message.trim(),
      },
      {
        onSuccess: () => {
          toast('success', 'Lead created.');
          reset();
          onClose();
        },
        onError: (err) => toast('error', err.message),
      },
    );
  });

  return (
    <Modal open={open} onClose={onClose} title="New lead">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <TextInput label="Name" required error={errors.display_name?.message} {...register('display_name', { required: 'Name is required.' })} />
        <div className="grid gap-4 sm:grid-cols-2">
          <TextInput label="Phone" placeholder="+91…" {...register('phone')} />
          <TextInput label="Email" type="email" {...register('email')} />
        </div>
        <TextInput label="Interest" placeholder="Trial, membership, seat…" {...register('service_interest')} />
        <TextArea label="Notes" {...register('message')} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={create.isPending}>Create lead</Button>
        </div>
      </form>
    </Modal>
  );
}
