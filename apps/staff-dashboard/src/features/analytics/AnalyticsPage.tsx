import { useState } from 'react';
import { useSession } from '../../lib/auth';
import { useIntelligence, useMetrics } from './hooks';
import { Card, PageHeader } from '../../components/ui/primitives';
import { CardsSkeleton, EmptyState, ErrorState, ForbiddenState } from '../../components/ui/states';
import { SelectInput } from '../../components/ui/forms';
import { formatMoney } from '../../lib/list';

/** Intelligence: metrics from real records + trend/driver/exception/action findings. */
export function AnalyticsPage(): JSX.Element {
  const { can } = useSession();
  const [days, setDays] = useState(30);
  if (!can('analytics.read')) return <ForbiddenState />;

  return (
    <div>
      <PageHeader
        title="Intelligence"
        subtitle="Every metric reproducible from source records"
        actions={
          <SelectInput
            label=""
            aria-label="Period"
            value={String(days)}
            onChange={(e) => setDays(Number(e.target.value))}
            options={[
              { value: '7', label: '7 days' },
              { value: '30', label: '30 days' },
              { value: '90', label: 'Quarter' },
            ]}
          />
        }
      />
      <div className="space-y-4">
        <MetricsCard days={days} />
        <FindingsCard days={days} />
      </div>
    </div>
  );
}

function MetricsCard({ days }: { days: number }): JSX.Element {
  const metrics = useMetrics(days);
  if (metrics.isPending) return <CardsSkeleton count={8} />;
  if (metrics.isError) {
    return (
      <ErrorState
        message={metrics.error instanceof Error ? metrics.error.message : 'Could not load metrics.'}
        onRetry={() => metrics.refetch()}
      />
    );
  }
  const m = metrics.data;
  const cards = [
    { label: 'Leads', value: String(m.leads) },
    { label: 'Conversion', value: `${m.conversion_rate}%` },
    { label: 'Revenue', value: formatMoney(m.revenue) },
    { label: 'Payments', value: String(m.payments) },
    { label: 'Active memberships', value: String(m.memberships_active) },
    { label: 'Renewals pending', value: String(m.renewals_pending) },
    { label: 'Attendance', value: String(m.attendance) },
    ...(m.seats_total
      ? [{ label: 'Occupancy', value: `${m.occupancy_rate}%` }]
      : [{ label: 'Members', value: String(m.members_total) }]),
  ];
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((c) => (
        <Card key={c.label}>
          <p className="truncate text-2xl font-black tabular-nums text-slate-900">{c.value}</p>
          <p className="text-sm text-slate-500">{c.label}</p>
        </Card>
      ))}
    </div>
  );
}

function FindingsCard({ days }: { days: number }): JSX.Element {
  const intel = useIntelligence(days);
  if (intel.isPending) return <CardsSkeleton count={3} />;
  if (intel.isError) {
    return (
      <ErrorState
        message={intel.error instanceof Error ? intel.error.message : 'Could not load intelligence.'}
        onRetry={() => intel.refetch()}
      />
    );
  }
  if (intel.data.findings.length === 0) {
    return <EmptyState title="No findings" message="Insights appear once there is activity to analyze." />;
  }
  return (
    <Card>
      <h2 className="mb-3 text-base font-bold text-slate-900">What changed — and what to do</h2>
      <ul className="space-y-3">
        {intel.data.findings.map((f) => (
          <li key={f.metric} className="rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200">
            <p className="text-xs font-bold uppercase tracking-wide text-slate-500">{f.metric}</p>
            <p className="mt-1 text-sm font-semibold text-slate-900">{f.trend}</p>
            <p className="mt-1 text-sm text-slate-600">{f.driver}</p>
            {f.exception ? (
              <p className="mt-1 text-sm text-amber-700" role="alert">
                {f.exception}
              </p>
            ) : null}
            <p className="mt-1 text-sm text-slate-700">
              <strong>Next:</strong> {f.possible_action}
            </p>
          </li>
        ))}
      </ul>
    </Card>
  );
}
