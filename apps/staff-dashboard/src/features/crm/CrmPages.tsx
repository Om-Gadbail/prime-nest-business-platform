import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { useSession } from '../../lib/auth';
import { useContact, useContacts, useCustomer, useCustomers, useUpdateContact, useUpdateCustomer } from './hooks';
import { useListParams, formatDateTime } from '../../lib/list';
import { Badge, Button, Card, PageHeader, StatusBadge } from '../../components/ui/primitives';
import { Modal } from '../../components/ui/overlays';
import { ErrorState, NoResults, TableSkeleton } from '../../components/ui/states';
import { Pagination, SelectInput, TextArea, TextInput } from '../../components/ui/forms';
import { useToast } from '../../components/ui/Toast';

/** Contacts: search, profile, notes, linked history entry points. */
export function ContactsPage(): JSX.Element {
  const { limit, offset, search, setOffset, setSearch } = useListParams();
  const [status, setStatus] = useState('');
  const query = useContacts({ search, status, limit, offset });

  return (
    <div>
      <PageHeader title="Contacts" subtitle="Reusable contact identities for this business" />
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <TextInput label="Search" placeholder="Name, phone, email…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <SelectInput
            label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}
            options={['', 'active', 'inactive', 'archived'].map((s) => ({ value: s, label: s === '' ? 'All' : s }))}
          />
          <div className="flex items-end">
            <Button variant="secondary" size="sm" onClick={() => { setSearch(''); setStatus(''); }}>Clear</Button>
          </div>
        </div>
      </Card>
      {query.isPending ? (
        <Card><TableSkeleton /></Card>
      ) : query.isError ? (
        <ErrorState message={query.error instanceof Error ? query.error.message : 'Could not load contacts.'} onRetry={() => query.refetch()} />
      ) : query.data.total === 0 ? (
        <NoResults />
      ) : (
        <Card className="p-0 sm:p-0">
          <ul className="divide-y divide-slate-100">
            {query.data.items.map((c) => (
              <li key={c.id}>
                <Link to={`/contacts/${c.id}`} className="flex flex-wrap items-center gap-2 px-5 py-3.5 hover:bg-slate-50 sm:gap-3">
                  <span className="min-w-0 flex-1 basis-48">
                    <span className="block truncate text-sm font-semibold text-slate-900">{c.display_name || 'Unnamed contact'}</span>
                    <span className="block truncate text-xs text-slate-500">{[c.phone, c.email].filter(Boolean).join(' · ') || '—'}</span>
                  </span>
                  <StatusBadge status={c.status} />
                  <span className="w-full text-xs text-slate-400 sm:w-auto">{formatDateTime(c.created_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
          <div className="px-5 pb-5">
            <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />
          </div>
        </Card>
      )}
    </div>
  );
}

export function ContactDetailPage(): JSX.Element {
  const { id = '' } = useParams();
  const { can } = useSession();
  const toast = useToast();
  const contact = useContact(id);
  const update = useUpdateContact(id);
  const [editOpen, setEditOpen] = useState(false);

  if (contact.isPending) return <Card><TableSkeleton /></Card>;
  if (contact.isError) {
    return <ErrorState title="Contact not found" message={contact.error instanceof Error ? contact.error.message : undefined} onRetry={() => contact.refetch()} />;
  }
  const c = contact.data;

  return (
    <div>
      <PageHeader title={c.display_name || 'Unnamed contact'} subtitle={`Since ${formatDateTime(c.created_at)}`} actions={<Link to="/contacts"><Button variant="secondary" size="sm">Back</Button></Link>} />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <div className="flex items-center gap-2">
            <StatusBadge status={c.status} />
            <Badge>{c.preferred_contact_channel}</Badge>
            <Badge>{c.source}</Badge>
          </div>
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
            <Read label="Phone" value={c.phone} />
            <Read label="Email" value={c.email} />
          </dl>
          {c.notes ? <p className="mt-4 rounded-xl bg-slate-50 p-3.5 text-sm text-slate-700 ring-1 ring-slate-200/60">{c.notes}</p> : null}
          {can('contacts.update') ? (
            <div className="mt-4">
              <Button size="sm" variant="secondary" onClick={() => setEditOpen(true)}>Edit contact</Button>
            </div>
          ) : null}
        </Card>
        <Card>
          <h2 className="mb-2 text-base font-bold text-slate-900">Related records</h2>
          <p className="text-sm text-slate-600">Leads and bookings linked to this contact appear under their modules — search the phone or email there.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Link to={`/leads?search=${encodeURIComponent(c.phone ?? c.email ?? '')}`}><Button size="sm" variant="secondary">Find leads</Button></Link>
            <Link to="/bookings"><Button size="sm" variant="secondary">Browse bookings</Button></Link>
          </div>
        </Card>
      </div>
      <EditContactModal open={editOpen} onClose={() => setEditOpen(false)} contactId={id} initial={{ notes: c.notes, preferred_contact_channel: c.preferred_contact_channel }} onSaved={() => toast('success', 'Contact updated.')} update={update} />
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

function EditContactModal({ open, onClose, initial, onSaved, update }: {
  open: boolean;
  onClose: () => void;
  contactId: string;
  initial: { notes: string; preferred_contact_channel: string };
  onSaved: () => void;
  update: ReturnType<typeof useUpdateContact>;
}): JSX.Element {
  const { register, handleSubmit } = useForm({ defaultValues: initial });
  return (
    <Modal open={open} onClose={onClose} title="Edit contact">
      <form
        onSubmit={handleSubmit((v) => {
          update.mutate(v, { onSuccess: () => { onSaved(); onClose(); } });
        })}
        className="space-y-4"
      >
        <SelectInput label="Preferred channel" {...register('preferred_contact_channel')} options={['call', 'whatsapp', 'email', 'other'].map((o) => ({ value: o, label: o }))} />
        <TextArea label="Notes" {...register('notes')} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={update.isPending}>Save</Button>
        </div>
      </form>
    </Modal>
  );
}

/** Customers: list, profile, notes. */
export function CustomersPage(): JSX.Element {
  const { limit, offset, setOffset } = useListParams();
  const [status, setStatus] = useState('');
  const query = useCustomers(status, limit, offset);

  return (
    <div>
      <PageHeader title="Customers" subtitle="Converted customer relationships" />
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <SelectInput
            label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}
            options={['', 'active', 'inactive', 'archived'].map((s) => ({ value: s, label: s === '' ? 'All' : s }))}
          />
          <div className="flex items-end">
            <Button variant="secondary" size="sm" onClick={() => setStatus('')}>Clear</Button>
          </div>
        </div>
      </Card>
      {query.isPending ? (
        <Card><TableSkeleton /></Card>
      ) : query.isError ? (
        <ErrorState message={query.error instanceof Error ? query.error.message : 'Could not load customers.'} onRetry={() => query.refetch()} />
      ) : query.data.total === 0 ? (
        <NoResults />
      ) : (
        <Card className="p-0 sm:p-0">
          <ul className="divide-y divide-slate-100">
            {query.data.items.map((c) => (
              <li key={c.id}>
                <Link to={`/customers/${c.id}`} className="flex flex-wrap items-center gap-2 px-5 py-3.5 hover:bg-slate-50 sm:gap-3">
                  <span className="min-w-0 flex-1 basis-48">
                    <span className="block truncate text-sm font-semibold text-slate-900">
                      {c.contact ? `${c.contact.first_name} ${c.contact.last_name}`.trim() || 'Customer' : 'Customer'}
                    </span>
                    <span className="block truncate text-xs text-slate-500">
                      {c.contact ? [c.contact.phone, c.contact.email].filter(Boolean).join(' · ') : ''}
                    </span>
                  </span>
                  <StatusBadge status={c.status} />
                  <span className="w-full text-xs text-slate-400 sm:w-auto">since {formatDateTime(c.customer_since)}</span>
                </Link>
              </li>
            ))}
          </ul>
          <div className="px-5 pb-5">
            <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />
          </div>
        </Card>
      )}
    </div>
  );
}

export function CustomerDetailPage(): JSX.Element {
  const { id = '' } = useParams();
  const { can } = useSession();
  const toast = useToast();
  const customer = useCustomer(id);
  const update = useUpdateCustomer(id);
  const [editOpen, setEditOpen] = useState(false);

  if (customer.isPending) return <Card><TableSkeleton /></Card>;
  if (customer.isError) {
    return <ErrorState title="Customer not found" message={customer.error instanceof Error ? customer.error.message : undefined} onRetry={() => customer.refetch()} />;
  }
  const c = customer.data;

  return (
    <div>
      <PageHeader
        title={c.contact ? `${c.contact.first_name} ${c.contact.last_name}`.trim() || 'Customer' : 'Customer'}
        subtitle={`Customer since ${formatDateTime(c.customer_since)}`}
        actions={<Link to="/customers"><Button variant="secondary" size="sm">Back</Button></Link>}
      />
      <Card>
        <StatusBadge status={c.status} />
        {c.contact ? (
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
            <Read label="Phone" value={c.contact.phone} />
            <Read label="Email" value={c.contact.email} />
          </dl>
        ) : null}
        {c.notes ? <p className="mt-4 rounded-xl bg-slate-50 p-3.5 text-sm text-slate-700 ring-1 ring-slate-200/60">{c.notes}</p> : null}
        {can('customers.update') ? (
          <div className="mt-4">
            <Button size="sm" variant="secondary" onClick={() => setEditOpen(true)}>Edit customer</Button>
          </div>
        ) : null}
      </Card>
      <Modal open={editOpen} onClose={() => setEditOpen(false)} title="Edit customer">
        <EditCustomerForm
          initial={{ notes: c.notes, status: c.status }}
          pending={update.isPending}
          onSubmit={(v) => update.mutate(v, { onSuccess: () => { toast('success', 'Customer updated.'); setEditOpen(false); } })}
          onCancel={() => setEditOpen(false)}
        />
      </Modal>
    </div>
  );
}

function EditCustomerForm({ initial, pending, onSubmit, onCancel }: {
  initial: { notes: string; status: string };
  pending: boolean;
  onSubmit: (v: { notes: string; status: string }) => void;
  onCancel: () => void;
}): JSX.Element {
  const { register, handleSubmit } = useForm({ defaultValues: initial });
  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <SelectInput label="Status" {...register('status')} options={['active', 'inactive', 'archived'].map((s) => ({ value: s, label: s }))} />
      <TextArea label="Notes" {...register('notes')} />
      <div className="flex justify-end gap-2">
        <Button variant="secondary" type="button" onClick={onCancel}>Cancel</Button>
        <Button type="submit" loading={pending}>Save</Button>
      </div>
    </form>
  );
}
