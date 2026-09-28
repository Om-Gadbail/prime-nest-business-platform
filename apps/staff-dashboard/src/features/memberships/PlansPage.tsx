import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Plus } from 'lucide-react';
import { useSession } from '../../lib/auth';
import { useCreatePlan, usePlans, useUpdatePlan } from './hooks';
import { useListParams } from '../../lib/list';
import { Badge, Button, Card, PageHeader } from '../../components/ui/primitives';
import { Modal } from '../../components/ui/overlays';
import { ErrorState, NoResults, TableSkeleton } from '../../components/ui/states';
import { Pagination, SelectInput, TextInput } from '../../components/ui/forms';
import { useToast } from '../../components/ui/Toast';
import { formatMoney } from '../../lib/list';
import type { MembershipPlan } from '../../types';

const CATEGORIES = ['', 'regular', 'confirmed', 'opening_regular', 'opening_confirmed', 'custom'];

/** Membership plans: data-driven catalogue (prices live in the backend). */
export function PlansPage(): JSX.Element {
  const { can } = useSession();
  const { limit, offset, search, setOffset, setSearch } = useListParams();
  const [category, setCategory] = useState('');
  const [editTarget, setEditTarget] = useState<MembershipPlan | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const query = usePlans({ category, search, limit, offset });
  const manageable = can('membership_plans.manage');

  return (
    <div>
      <PageHeader
        title="Membership plans"
        subtitle="Catalogue data — edits never rewrite member history"
        actions={
          manageable ? (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden /> New plan
            </Button>
          ) : undefined
        }
      />
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <TextInput label="Search" placeholder="Name or code…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <SelectInput label="Category" value={category} onChange={(e) => { setCategory(e.target.value); setOffset(0); }}
            options={CATEGORIES.map((c) => ({ value: c, label: c === '' ? 'All categories' : c.replace(/_/g, ' ') }))} />
          <div className="flex items-end">
            <Button variant="secondary" size="sm" onClick={() => { setSearch(''); setCategory(''); }}>Clear</Button>
          </div>
        </div>
      </Card>
      {query.isPending ? (
        <Card><TableSkeleton /></Card>
      ) : query.isError ? (
        <ErrorState message={query.error instanceof Error ? query.error.message : 'Could not load plans.'} onRetry={() => query.refetch()} />
      ) : query.data.total === 0 ? (
        <NoResults onClear={() => { setSearch(''); setCategory(''); }} />
      ) : (
        <div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {query.data.items.map((p) => (
              <Card key={p.id} className={p.is_best_value ? 'ring-2 ring-amber-300' : ''}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <h2 className="truncate text-base font-bold text-slate-900">{p.name}</h2>
                    <p className="truncate text-xs text-slate-500">{p.code} · {p.duration_months} mo</p>
                  </div>
                  {p.is_best_value ? <Badge tone="amber">Best value</Badge> : null}
                </div>
                <p className="mt-2 text-2xl font-black tabular-nums text-slate-900">{formatMoney(p.price, p.currency)}</p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Badge>{p.category.replace(/_/g, ' ')}</Badge>
                  {!p.is_active ? <Badge tone="rose">Archived</Badge> : null}
                  {manageable ? (
                    <button type="button" onClick={() => setEditTarget(p)}
                      className="ml-auto cursor-pointer text-sm font-semibold text-slate-600 hover:text-slate-900">
                      Edit
                    </button>
                  ) : null}
                </div>
              </Card>
            ))}
          </div>
          <Card className="mt-4">
            <Pagination total={query.data.total} limit={limit} offset={offset} onChange={setOffset} />
          </Card>
        </div>
      )}
      <PlanModal open={createOpen} onClose={() => setCreateOpen(false)} target={null} />
      <PlanModal open={Boolean(editTarget)} onClose={() => setEditTarget(null)} target={editTarget} />
    </div>
  );
}

function PlanModal({ open, onClose, target }: { open: boolean; onClose: () => void; target: MembershipPlan | null }): JSX.Element {
  const toast = useToast();
  const create = useCreatePlan();
  const update = useUpdatePlan(target?.id ?? '');
  const { register, handleSubmit, reset } = useForm({
    defaultValues: { code: '', name: '', category: 'custom', duration_months: 1, price: '', is_best_value: false, is_active: true },
    values: target
      ? { code: target.code, name: target.name, category: target.category, duration_months: target.duration_months, price: target.price, is_best_value: target.is_best_value, is_active: target.is_active }
      : undefined,
  });
  const pending = create.isPending || update.isPending;
  const onSubmit = handleSubmit((values) => {
    const body: Record<string, unknown> = {
      name: values.name.trim(),
      category: values.category,
      duration_months: Number(values.duration_months),
      price: values.price,
      is_best_value: Boolean(values.is_best_value),
      is_active: Boolean(values.is_active),
    };
    if (!target) body.code = values.code.trim();
    const mutation = target ? update : create;
    mutation.mutate(body, {
      onSuccess: () => { toast('success', target ? 'Plan updated.' : 'Plan created.'); reset(); onClose(); },
      onError: (err) => toast('error', err.message),
    });
  });
  return (
    <Modal open={open} onClose={onClose} title={target ? 'Edit plan' : 'New plan'}>
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {!target ? <TextInput label="Code" required placeholder="nest-regular-1m" {...register('code', { required: 'Code is required.' })} /> : null}
        <TextInput label="Name" required {...register('name', { required: 'Name is required.' })} />
        <div className="grid gap-4 sm:grid-cols-2">
          <SelectInput label="Category" {...register('category')}
            options={CATEGORIES.filter(Boolean).map((c) => ({ value: c, label: c.replace(/_/g, ' ') }))} />
          <TextInput label="Duration (months)" type="number" min={1} max={60} {...register('duration_months', { valueAsNumber: true })} />
        </div>
        <TextInput label="Price" required inputMode="decimal" placeholder="0.00" {...register('price', { required: 'Price is required.' })} />
        <div className="flex flex-wrap gap-4 text-sm">
          <label className="inline-flex min-h-[44px] items-center gap-2 font-medium text-slate-700">
            <input type="checkbox" {...register('is_best_value')} className="h-5 w-5" /> Best value
          </label>
          <label className="inline-flex min-h-[44px] items-center gap-2 font-medium text-slate-700">
            <input type="checkbox" {...register('is_active')} className="h-5 w-5" /> Active
          </label>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={pending}>{target ? 'Save' : 'Create'}</Button>
        </div>
      </form>
    </Modal>
  );
}
