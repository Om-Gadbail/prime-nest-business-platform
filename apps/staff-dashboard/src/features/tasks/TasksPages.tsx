import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { Plus } from 'lucide-react';
import { useSession } from '../../lib/auth';
import { useAssignTask, useCreateTask, useSetTaskStatus, useTask, useTasks, useUpdateTask } from './hooks';
import { dueLabel, formatDateTime, useListParams } from '../../lib/list';
import { Button, Card, PageHeader, PriorityBadge, StatusBadge } from '../../components/ui/primitives';
import { Modal } from '../../components/ui/overlays';
import { ErrorState, NoResults, TableSkeleton } from '../../components/ui/states';
import { Pagination, SelectInput, TextArea, TextInput } from '../../components/ui/forms';
import { useToast } from '../../components/ui/Toast';

const STATUSES = ['', 'open', 'in_progress', 'completed', 'cancelled'];
const PRIORITIES = ['', 'low', 'medium', 'high', 'urgent'];
const NEXT_TASK: Record<string, string[]> = {
  open: ['in_progress', 'completed', 'cancelled'],
  in_progress: ['completed', 'cancelled'],
  completed: ['open'],
  cancelled: ['open'],
};

/** Tasks: assigned-to-me, due today, overdue, completed, create, detail. */
export function TasksPage(): JSX.Element {
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const { limit, offset, search, setOffset, setSearch } = useListParams();
  const [status, setStatus] = useState('');
  const [priority, setPriority] = useState('');
  const [view, setView] = useState<'all' | 'mine' | 'overdue' | 'completed'>(
    params.get('mine') === '1' ? 'mine' : params.get('overdue') === 'true' ? 'overdue' : 'all',
  );
  const [createOpen, setCreateOpen] = useState(params.get('new') === '1');

  const query = useTasks({
    status: view === 'completed' ? 'completed' : status,
    priority,
    overdue_only: view === 'overdue',
    mine_only: view === 'mine',
    search,
    limit,
    offset,
  });

  const setViewAndReset = (v: typeof view): void => {
    setView(v);
    setOffset(0);
    setParams({});
  };

  return (
    <div>
      <PageHeader
        title="Tasks"
        subtitle="Operational follow-ups for this business"
        actions={
          can('tasks.create') ? (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden /> New task
            </Button>
          ) : undefined
        }
      />
      <div role="tablist" aria-label="Task views" className="mb-4 flex gap-2 overflow-x-auto">
        {(['all', 'mine', 'overdue', 'completed'] as const).map((v) => (
          <button
            key={v}
            role="tab"
            aria-selected={view === v}
            onClick={() => setViewAndReset(v)}
            className={`h-10 shrink-0 cursor-pointer rounded-xl px-4 text-sm font-semibold ring-1 transition ${
              view === v ? 'bg-slate-900 text-white ring-slate-900' : 'bg-white text-slate-600 ring-slate-300 hover:bg-slate-50'
            }`}
          >
            {v === 'mine' ? 'Assigned to me' : v === 'overdue' ? 'Overdue' : v[0].toUpperCase() + v.slice(1)}
          </button>
        ))}
      </div>
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <TextInput label="Search" placeholder="Title, description…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <SelectInput label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} options={STATUSES.map((s) => ({ value: s, label: s === '' ? 'All statuses' : s.replace(/_/g, ' ') }))} />
          <SelectInput label="Priority" value={priority} onChange={(e) => { setPriority(e.target.value); setOffset(0); }} options={PRIORITIES.map((s) => ({ value: s, label: s === '' ? 'All priorities' : s }))} />
          <div className="flex items-end">
            <Button variant="secondary" size="sm" onClick={() => { setSearch(''); setStatus(''); setPriority(''); setViewAndReset('all'); }}>Clear</Button>
          </div>
        </div>
      </Card>
      {query.isPending ? (
        <Card><TableSkeleton /></Card>
      ) : query.isError ? (
        <ErrorState message={query.error instanceof Error ? query.error.message : 'Could not load tasks.'} onRetry={() => query.refetch()} />
      ) : query.data.total === 0 ? (
        <NoResults />
      ) : (
        <Card className="p-0 sm:p-0">
          <ul className="divide-y divide-slate-100">
            {query.data.items.map((t) => {
              const due = dueLabel(t.due_at);
              return (
                <li key={t.id}>
                  <Link to={`/tasks/${t.id}`} className="flex flex-wrap items-center gap-2 px-5 py-3.5 hover:bg-slate-50 sm:gap-3">
                    <span className="min-w-0 flex-1 basis-48">
                      <span className="block truncate text-sm font-semibold text-slate-900">{t.title}</span>
                      <span className={`block truncate text-xs ${due.overdue ? 'font-semibold text-rose-600' : 'text-slate-500'}`}>{due.text}</span>
                    </span>
                    <PriorityBadge priority={t.priority} />
                    <StatusBadge status={t.status} />
                    <span className="w-full text-xs text-slate-400 sm:w-auto">{formatDateTime(t.created_at)}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
          <div className="px-5 pb-5">
            <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />
          </div>
        </Card>
      )}
      <CreateTaskModal open={createOpen} onClose={() => { setCreateOpen(false); setParams({}); }} />
    </div>
  );
}

export function TaskDetailPage(): JSX.Element {
  const { id = '' } = useParams();
  const { can } = useSession();
  const toast = useToast();
  const task = useTask(id);
  const setStatus = useSetTaskStatus(id);
  const assign = useAssignTask(id);
  const update = useUpdateTask(id);
  const [assignOpen, setAssignOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);

  if (task.isPending) return <Card><TableSkeleton /></Card>;
  if (task.isError) {
    return <ErrorState title="Task not found" message={task.error instanceof Error ? task.error.message : undefined} onRetry={() => task.refetch()} />;
  }
  const t = task.data;
  const next = NEXT_TASK[t.status.toLowerCase()] ?? [];
  const due = dueLabel(t.due_at);

  const move = (status: string): void => {
    setStatus.mutate(
      { status },
      {
        onSuccess: (updated) => toast('success', `Task ${updated.status.replace(/_/g, ' ')}.`),
        onError: (e) => toast('error', e.message),
      },
    );
  };

  return (
    <div>
      <PageHeader title={t.title} subtitle={`Created ${formatDateTime(t.created_at)}`} actions={<Link to="/tasks"><Button variant="secondary" size="sm">Back</Button></Link>} />
      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={t.status} />
            <PriorityBadge priority={t.priority} />
          </div>
          {t.description ? <p className="mt-4 rounded-xl bg-slate-50 p-3.5 text-sm text-slate-700 ring-1 ring-slate-200/60">{t.description}</p> : null}
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">Due</dt>
              <dd className={`text-sm font-medium ${due.overdue ? 'text-rose-600' : 'text-slate-800'}`}>{due.text} · {formatDateTime(t.due_at)}</dd>
            </div>
            {t.related_entity_type ? (
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">Linked record</dt>
                <dd className="text-sm font-medium text-slate-800">{t.related_entity_type} — {t.related_entity_id?.slice(0, 8)}…</dd>
              </div>
            ) : null}
            {t.completed_at ? (
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">Completed</dt>
                <dd className="text-sm font-medium text-slate-800">{formatDateTime(t.completed_at)}</dd>
              </div>
            ) : null}
          </dl>
          {can('tasks.update') ? (
            <div className="mt-4 flex flex-wrap gap-2">
              {next.map((s) => (
                <Button key={s} size="sm" variant={s === 'completed' ? 'primary' : 'secondary'} onClick={() => move(s)} loading={setStatus.isPending}>
                  {s === 'open' ? 'Reopen' : `Mark ${s.replace(/_/g, ' ')}`}
                </Button>
              ))}
              <Button size="sm" variant="secondary" onClick={() => setAssignOpen(true)}>Assign</Button>
              <Button size="sm" variant="secondary" onClick={() => setEditOpen(true)}>Edit</Button>
            </div>
          ) : null}
        </Card>
      </div>
      <Modal open={assignOpen} onClose={() => setAssignOpen(false)} title="Assign task">
        <AssignForm
          pending={assign.isPending}
          onSubmit={(userId) => assign.mutate({ assigned_to_user_id: userId }, {
            onSuccess: () => { toast('success', 'Task assigned.'); setAssignOpen(false); },
            onError: (e) => toast('error', e.message),
          })}
          onCancel={() => setAssignOpen(false)}
        />
      </Modal>
      <Modal open={editOpen} onClose={() => setEditOpen(false)} title="Edit task">
        <EditForm
          initial={{ title: t.title, description: t.description, priority: t.priority, due_at: t.due_at ? t.due_at.slice(0, 16) : '' }}
          pending={update.isPending}
          onSubmit={(v) => update.mutate({
            title: v.title,
            description: v.description,
            priority: v.priority,
            due_at: v.due_at ? new Date(v.due_at).toISOString() : null,
          }, {
            onSuccess: () => { toast('success', 'Task updated.'); setEditOpen(false); },
            onError: (e) => toast('error', e.message),
          })}
          onCancel={() => setEditOpen(false)}
        />
      </Modal>
    </div>
  );
}

function AssignForm({ pending, onSubmit, onCancel }: { pending: boolean; onSubmit: (userId: string) => void; onCancel: () => void }): JSX.Element {
  const { register, handleSubmit } = useForm<{ assigned_to_user_id: string }>({ defaultValues: { assigned_to_user_id: '' } });
  return (
    <form onSubmit={handleSubmit((v) => onSubmit(v.assigned_to_user_id))} className="space-y-4">
      <TextInput label="Assignee user ID" required hint="Paste the staff member's user ID." {...register('assigned_to_user_id', { required: 'User ID is required.' })} />
      <div className="flex justify-end gap-2">
        <Button variant="secondary" type="button" onClick={onCancel}>Cancel</Button>
        <Button type="submit" loading={pending}>Assign</Button>
      </div>
    </form>
  );
}

function EditForm({ initial, pending, onSubmit, onCancel }: {
  initial: { title: string; description: string; priority: string; due_at: string };
  pending: boolean;
  onSubmit: (v: { title: string; description: string; priority: string; due_at: string }) => void;
  onCancel: () => void;
}): JSX.Element {
  const { register, handleSubmit } = useForm({ defaultValues: initial });
  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <TextInput label="Title" required {...register('title', { required: 'Title is required.' })} />
      <TextArea label="Description" {...register('description')} />
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectInput label="Priority" {...register('priority')} options={['low', 'medium', 'high', 'urgent'].map((p) => ({ value: p, label: p }))} />
        <TextInput label="Due" type="datetime-local" {...register('due_at')} />
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" type="button" onClick={onCancel}>Cancel</Button>
        <Button type="submit" loading={pending}>Save</Button>
      </div>
    </form>
  );
}

function CreateTaskModal({ open, onClose }: { open: boolean; onClose: () => void }): JSX.Element {
  const toast = useToast();
  const create = useCreateTask();
  const { register, handleSubmit, reset } = useForm<{ title: string; description: string; priority: string; due_at: string }>({
    defaultValues: { title: '', description: '', priority: 'medium', due_at: '' },
  });
  const onSubmit = handleSubmit((v) => {
    create.mutate(
      {
        title: v.title,
        description: v.description,
        priority: v.priority,
        due_at: v.due_at ? new Date(v.due_at).toISOString() : null,
      },
      {
        onSuccess: () => { toast('success', 'Task created.'); reset(); onClose(); },
        onError: (e) => toast('error', e.message),
      },
    );
  });
  return (
    <Modal open={open} onClose={onClose} title="New task">
      <form onSubmit={onSubmit} className="space-y-4">
        <TextInput label="Title" required {...register('title', { required: 'Title is required.' })} />
        <TextArea label="Description" {...register('description')} />
        <div className="grid gap-4 sm:grid-cols-2">
          <SelectInput label="Priority" {...register('priority')} options={['low', 'medium', 'high', 'urgent'].map((p) => ({ value: p, label: p }))} />
          <TextInput label="Due" type="datetime-local" {...register('due_at')} />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={create.isPending}>Create task</Button>
        </div>
      </form>
    </Modal>
  );
}
