import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { useSession } from '../../lib/auth';
import { keys } from '../../lib/query';
import { api } from '../../lib/api';
import { Button, Card, PageHeader } from '../../components/ui/primitives';
import { ErrorState, ForbiddenState, TableSkeleton } from '../../components/ui/states';
import { useToast } from '../../components/ui/Toast';
import type { BusinessSettings } from '../../types';

function useSettings(): ReturnType<typeof useQuery<BusinessSettings>> {
  const { businessId, can } = useSession();
  return useQuery({
    queryKey: keys.settings(businessId ?? 'none'),
    queryFn: () => api.get<BusinessSettings>('/api/v1/business/settings'),
    enabled: Boolean(businessId && can('settings.read')),
  });
}

/** Settings: only what the current role may access (backend enforces). */
export function SettingsPage(): JSX.Element {
  const { me, can, role } = useSession();
  const toast = useToast();
  const settings = useSettings();
  const client = useQueryClient();
  const businessId = me?.business?.id ?? '';

  const updateOperational = useMutation({
    mutationFn: (operational: Record<string, boolean>) =>
      api.patch<BusinessSettings>('/api/v1/business/settings', { operational }),
    onSuccess: (data) => {
      client.setQueryData(keys.settings(businessId), data);
      toast('success', 'Settings updated.');
    },
    onError: (err: unknown) => toast('error', err instanceof Error ? err.message : 'Update failed.'),
  });

  if (!can('settings.read')) {
    return (
      <div>
        <PageHeader title="Settings" />
        <ForbiddenState />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="Settings" subtitle={`Signed in as ${me?.user.email} · role ${role ?? '—'}`} />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <h2 className="mb-1 text-base font-bold text-slate-900">Business</h2>
          <dl className="mt-2 space-y-2 text-sm">
            <Row label="Name" value={me?.business?.name} />
            <Row label="Slug" value={me?.business?.slug} />
            <Row label="Type" value={me?.business?.business_type} />
            <Row label="Status" value={me?.business?.status} />
          </dl>
        </Card>

        <Card>
          <h2 className="mb-1 text-base font-bold text-slate-900">Public intake flags</h2>
          {settings.isPending ? (
            <TableSkeleton rows={2} cols={2} />
          ) : settings.isError ? (
            <ErrorState message="Could not load settings." onRetry={() => settings.refetch()} />
          ) : (
            <OperationalForm
              initial={{
                lead_capture_enabled: operationalFlag(settings.data, 'lead_capture_enabled'),
                booking_enabled: operationalFlag(settings.data, 'booking_enabled'),
              }}
              disabled={!can('settings.update')}
              pending={updateOperational.isPending}
              onSubmit={(v) => updateOperational.mutate(v)}
            />
          )}
          {!can('settings.update') ? (
            <p className="mt-3 text-xs text-slate-500">Your role is read-only for settings. Ask an Owner/Admin to change these.</p>
          ) : null}
        </Card>

        <Card>
          <h2 className="mb-1 text-base font-bold text-slate-900">Contact preview</h2>
          <p className="mb-3 text-sm text-slate-500">Stored contact details (read-only here; Owners edit via API).</p>
          {settings.data ? (
            <dl className="space-y-2 text-sm">
              <Row label="Phone" value={str(settings.data.contact?.['phone'])} />
              <Row label="Email" value={str(settings.data.contact?.['email'])} />
              <Row label="Timezone" value={str(settings.data.localization?.['timezone'])} />
            </dl>
          ) : (
            <p className="text-sm text-slate-500">—</p>
          )}
        </Card>

        <Card>
          <h2 className="mb-1 text-base font-bold text-slate-900">Your permissions</h2>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {(me?.permissions ?? []).map((p) => (
              <li key={p} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600 ring-1 ring-slate-200">
                {p}
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value?: string | null }): JSX.Element {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-slate-500">{label}</dt>
      <dd className="truncate font-semibold text-slate-800">{value && value.trim() ? value : '—'}</dd>
    </div>
  );
}

function str(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function operationalFlag(settings: BusinessSettings, flag: string): boolean {
  const value = (settings.operational as Record<string, unknown> | undefined)?.[flag];
  return value !== false;
}

function OperationalForm({ initial, disabled, pending, onSubmit }: {
  initial: { lead_capture_enabled: boolean; booking_enabled: boolean };
  disabled: boolean;
  pending: boolean;
  onSubmit: (v: { lead_capture_enabled: boolean; booking_enabled: boolean }) => void;
}): JSX.Element {
  const { register, handleSubmit } = useForm({ defaultValues: initial });
  return (
    <form onSubmit={handleSubmit(onSubmit)} className="mt-2 space-y-3">
      {(['lead_capture_enabled', 'booking_enabled'] as const).map((flag) => (
        <label key={flag} className="flex min-h-[48px] cursor-pointer items-center justify-between gap-3 rounded-xl bg-slate-50 px-3.5 ring-1 ring-slate-200/60">
          <span className="text-sm font-medium text-slate-700">{flag.replace(/_/g, ' ')}</span>
          <input
            type="checkbox"
            disabled={disabled}
            {...register(flag)}
            className="h-5 w-5 cursor-pointer accent-slate-900 disabled:cursor-not-allowed"
          />
        </label>
      ))}
      {disabled ? null : (
        <Button type="submit" size="sm" loading={pending}>Save flags</Button>
      )}
    </form>
  );
}
