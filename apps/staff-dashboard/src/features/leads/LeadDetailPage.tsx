import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useSession } from '../../lib/auth';
import {
  useAddLeadNote,
  useAssignLead,
  useConvertLead,
  useLead,
  useLeadActivities,
  useSetLeadStatus,
  useTransferLead,
} from './hooks';
import { Badge, Button, Card, PageHeader, StatusBadge } from '../../components/ui/primitives';
import { Modal } from '../../components/ui/overlays';
import { ErrorState, TableSkeleton } from '../../components/ui/states';
import { SelectInput, TextArea, TextInput } from '../../components/ui/forms';
import { useToast } from '../../components/ui/Toast';
import { formatDateTime } from '../../lib/list';

const NEXT_STATUS: Record<string, string[]> = {
  new: ['contacted', 'qualified', 'lost', 'spam'],
  contacted: ['qualified', 'booked', 'lost', 'spam'],
  qualified: ['booked', 'contacted', 'lost', 'spam'],
  booked: ['converted', 'contacted', 'lost', 'spam'],
  lost: ['new'],
  converted: [],
  spam: [],
};

/** Lead detail: profile, routing lineage, activity timeline, actions. */
export function LeadDetailPage(): JSX.Element {
  const { id = '' } = useParams();
  const { can, role } = useSession();
  const navigate = useNavigate();
  const toast = useToast();
  const lead = useLead(id);
  const activities = useLeadActivities(id);
  const [noteOpen, setNoteOpen] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [transferOpen, setTransferOpen] = useState(false);
  const [convertOpen, setConvertOpen] = useState(false);

  if (lead.isPending) return <Card><TableSkeleton /></Card>;
  if (lead.isError) {
    return (
      <ErrorState
        title={lead.error instanceof Error && lead.error.message === 'Not found.' ? 'Lead not found' : 'Could not load the lead'}
        message={lead.error instanceof Error ? lead.error.message : undefined}
        onRetry={() => lead.refetch()}
      />
    );
  }

  const data = lead.data;
  const next = NEXT_STATUS[data.status.toLowerCase()] ?? [];

  return (
    <div>
      <PageHeader
        title={data.display_name || 'Unnamed lead'}
        subtitle={`Created ${formatDateTime(data.created_at)} · via ${data.source}`}
        actions={<Button variant="secondary" size="sm" onClick={() => navigate('/leads')}>Back to leads</Button>}
      />

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={data.status} />
              <Badge>{data.source}</Badge>
              {data.service_interest ? <Badge tone="blue">{data.service_interest}</Badge> : null}
            </div>
            <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
              <Detail label="Phone" value={data.phone} href={data.phone ? `tel:${data.phone}` : undefined} />
              <Detail label="Email" value={data.email} href={data.email ? `mailto:${data.email}` : undefined} />
              <Detail label="Interest" value={data.service_interest} />
              <Detail label="Source detail" value={data.source_detail} />
              <Detail label="Follow-up" value={formatDateTime(data.follow_up_at)} />
              <Detail label="Last contacted" value={formatDateTime(data.last_contacted_at)} />
              {data.lost_reason ? <Detail label="Lost reason" value={data.lost_reason} /> : null}
              {data.customer_id ? (
                <Detail label="Customer" value="Converted — view customer" href={`/customers`} />
              ) : null}
            </dl>
            {data.message ? (
              <div className="mt-4 rounded-xl bg-slate-50 p-3.5 text-sm text-slate-700 ring-1 ring-slate-200/60">
                {data.message}
              </div>
            ) : null}
            <div className="mt-4 flex flex-wrap gap-2">
              {can('leads.update') ? (
                <>
                  <Button size="sm" variant="secondary" onClick={() => setNoteOpen(true)}>Add note</Button>
                  {next.length > 0 ? <Button size="sm" variant="secondary" onClick={() => setStatusOpen(true)}>Change status</Button> : null}
                  <Button size="sm" variant="secondary" onClick={() => setAssignOpen(true)}>Assign</Button>
                </>
              ) : null}
              {can('leads.update') && can('customers.create') && data.status !== 'converted' ? (
                <Button size="sm" onClick={() => setConvertOpen(true)}>Convert to customer</Button>
              ) : null}
              {(role === 'OWNER' || role === 'ADMIN') && can('leads.transfer') ? (
                <Button size="sm" variant="secondary" onClick={() => setTransferOpen(true)}>Transfer business</Button>
              ) : null}
            </div>
          </Card>

          <Card>
            <h2 className="mb-3 text-base font-bold text-slate-900">Activity timeline</h2>
            {activities.isPending ? (
              <TableSkeleton rows={3} cols={2} />
            ) : activities.isError ? (
              <p className="text-sm text-slate-500">Could not load activity.</p>
            ) : activities.data.total === 0 ? (
              <p className="py-4 text-center text-sm text-slate-500">No activity yet.</p>
            ) : (
              <ol className="space-y-3">
                {activities.data.items.map((a) => (
                  <li key={a.id} className="border-l-2 border-slate-200 pl-3">
                    <p className="text-sm font-semibold text-slate-800">{a.activity_type.replace(/_/g, ' ')}</p>
                    <p className="text-sm text-slate-600">{a.note}</p>
                    <p className="text-xs text-slate-400">{formatDateTime(a.created_at)}</p>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <h2 className="mb-2 text-base font-bold text-slate-900">Routing lineage</h2>
            <dl className="space-y-2 text-sm">
              <Detail label="Routed by" value={data.routed_by} />
              <Detail label="Reason" value={data.routing_reason || '—'} />
              <Detail label="Routed at" value={formatDateTime(data.routed_at)} />
              {data.landing_page ? <Detail label="Landing page" value={data.landing_page} /> : null}
              {data.utm_source ? <Detail label="Campaign" value={`${data.utm_source} / ${data.utm_campaign}`} /> : null}
            </dl>
          </Card>
          {data.contact_id ? (
            <Card>
              <h2 className="mb-2 text-base font-bold text-slate-900">Linked contact</h2>
              <Link to={`/contacts?search=${encodeURIComponent(data.phone ?? data.email ?? '')}`} className="text-sm font-semibold text-slate-700 hover:text-slate-900">
                Open in contacts →
              </Link>
            </Card>
          ) : null}
        </div>
      </div>

      <NoteModal open={noteOpen} onClose={() => setNoteOpen(false)} leadId={id} />
      <StatusModal open={statusOpen} onClose={() => setStatusOpen(false)} leadId={id} current={data.status} options={next} />
      <AssignModal open={assignOpen} onClose={() => setAssignOpen(false)} leadId={id} />
      <TransferModal open={transferOpen} onClose={() => setTransferOpen(false)} leadId={id} />
      <ConvertDialog open={convertOpen} onClose={() => setConvertOpen(false)} leadId={id} toast={toast} />
    </div>
  );
}

function Detail({ label, value, href }: { label: string; value?: string | null; href?: string }): JSX.Element {
  const text = value && value.trim() ? value : '—';
  return (
    <div className="min-w-0">
      <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="truncate text-sm font-medium text-slate-800" title={text}>
        {href && value ? <a href={href} className="text-slate-900 underline decoration-slate-300 underline-offset-2">{text}</a> : text}
      </dd>
    </div>
  );
}

function NoteModal({ open, onClose, leadId }: { open: boolean; onClose: () => void; leadId: string }): JSX.Element {
  const toast = useToast();
  const add = useAddLeadNote(leadId);
  const { register, handleSubmit, reset } = useForm<{ note: string }>({ defaultValues: { note: '' } });
  const onSubmit = handleSubmit((v) => {
    add.mutate(
      { note: v.note },
      {
        onSuccess: () => { toast('success', 'Note added.'); reset(); onClose(); },
        onError: (e) => toast('error', e.message),
      },
    );
  });
  return (
    <Modal open={open} onClose={onClose} title="Add note">
      <form onSubmit={onSubmit} className="space-y-4">
        <TextArea label="Note" required {...register('note', { required: 'Note is required.' })} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={add.isPending}>Save note</Button>
        </div>
      </form>
    </Modal>
  );
}

function StatusModal({ open, onClose, leadId, current, options }: { open: boolean; onClose: () => void; leadId: string; current: string; options: string[] }): JSX.Element {
  const toast = useToast();
  const set = useSetLeadStatus(leadId);
  const { register, handleSubmit, watch } = useForm<{ status: string; lost_reason: string; note: string }>({
    defaultValues: { status: options[0] ?? current, lost_reason: '', note: '' },
  });
  const status = watch('status');
  const onSubmit = handleSubmit((v) => {
    set.mutate(v, {
      onSuccess: () => { toast('success', `Lead moved to ${v.status}.`); onClose(); },
      onError: (e) => toast('error', e.message),
    });
  });
  return (
    <Modal open={open} onClose={onClose} title="Change status">
      <form onSubmit={onSubmit} className="space-y-4">
        <SelectInput label="New status" {...register('status')} options={options.map((s) => ({ value: s, label: s }))} />
        {status === 'lost' ? <TextArea label="Lost reason" required hint="Required to mark a lead lost." {...register('lost_reason')} /> : null}
        <TextArea label="Note (optional)" {...register('note')} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={set.isPending}>Update status</Button>
        </div>
      </form>
    </Modal>
  );
}

function AssignModal({ open, onClose, leadId }: { open: boolean; onClose: () => void; leadId: string }): JSX.Element {
  const toast = useToast();
  const assign = useAssignLead(leadId);
  const { register, handleSubmit } = useForm<{ assigned_user_id: string }>({ defaultValues: { assigned_user_id: '' } });
  const onSubmit = handleSubmit((v) => {
    assign.mutate(
      { assigned_user_id: v.assigned_user_id },
      {
        onSuccess: () => { toast('success', 'Lead assigned.'); onClose(); },
        onError: (e) => toast('error', e.message),
      },
    );
  });
  return (
    <Modal open={open} onClose={onClose} title="Assign lead">
      <form onSubmit={onSubmit} className="space-y-4">
        <TextInput label="Assignee user ID" required hint="Paste the staff member's user ID." {...register('assigned_user_id', { required: 'User ID is required.' })} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={assign.isPending}>Assign</Button>
        </div>
      </form>
    </Modal>
  );
}

function TransferModal({ open, onClose, leadId }: { open: boolean; onClose: () => void; leadId: string }): JSX.Element {
  const toast = useToast();
  const transfer = useTransferLead(leadId);
  const { register, handleSubmit } = useForm<{ target_business_slug: string; reason: string }>({
    defaultValues: { target_business_slug: '', reason: '' },
  });
  const onSubmit = handleSubmit((v) => {
    transfer.mutate(v, {
      onSuccess: () => { toast('success', 'Lead transferred with an audit trail.'); onClose(); },
      onError: (e) => toast('error', e.message),
    });
  });
  return (
    <Modal open={open} onClose={onClose} title="Transfer to another business">
      <form onSubmit={onSubmit} className="space-y-4">
        <p className="text-sm text-slate-600">
          Creates a linked copy in the target business. The source row stays. Owner/Admin only.
        </p>
        <TextInput label="Target business slug" required placeholder="prime or nest" {...register('target_business_slug', { required: 'Target is required.' })} />
        <TextArea label="Reason" required hint="At least 10 characters — recorded in the audit trail." {...register('reason', { required: 'Reason is required.', minLength: { value: 10, message: 'At least 10 characters.' } })} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={transfer.isPending}>Transfer</Button>
        </div>
      </form>
    </Modal>
  );
}

function ConvertDialog({ open, onClose, leadId, toast }: { open: boolean; onClose: () => void; leadId: string; toast: (k: 'success' | 'error', m: string) => void }): JSX.Element {
  const convert = useConvertLead(leadId);
  const { register, handleSubmit } = useForm<{ customer_notes: string }>({ defaultValues: { customer_notes: '' } });
  const onSubmit = handleSubmit((v) => {
    convert.mutate(v, {
      onSuccess: () => { toast('success', 'Lead converted to customer.'); onClose(); },
      onError: (e) => toast('error', e.message),
    });
  });
  return (
    <Modal open={open} onClose={onClose} title="Convert to customer">
      <form onSubmit={onSubmit} className="space-y-4">
        <TextArea label="Customer notes (optional)" {...register('customer_notes')} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={convert.isPending}>Convert</Button>
        </div>
      </form>
    </Modal>
  );
}
