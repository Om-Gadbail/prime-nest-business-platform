import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, RefreshCw } from 'lucide-react';
import { useSession } from '../../lib/auth';
import { useOwnerCombined, useOwnerLeads, useOwnerOverview, useOwnerRevenue, type RangePreset } from './hooks';
import { Badge, Card, PageHeader, StatusBadge } from '../../components/ui/primitives';
import { CardsSkeleton, EmptyState, ErrorState, ForbiddenState } from '../../components/ui/states';
import { SelectInput } from '../../components/ui/forms';
import { formatDateTime, formatMoney, formatRate } from '../../lib/list';
import type { CombinedBusinessItem, OwnerBusinessOverview } from '../../types';

const PRESETS: Array<{ value: RangePreset; label: string }> = [
  { value: 'today', label: 'Today' },
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: 'month', label: 'This month' },
  { value: 'quarter', label: 'Quarter' },
  { value: 'all', label: 'All time' },
];

/**
 * Owner Command Center: what is happening, what needs attention, and how
 * every business performs. All figures are live backend aggregates —
 * empty businesses render zeros, never invented metrics.
 */
export function OwnerPage(): JSX.Element {
  const { can } = useSession();
  const [preset, setPreset] = useState<RangePreset>('30d');
  const [scope, setScope] = useState('all');
  const showCombined = can('owner.combined.read');

  if (!can('owner.dashboard.read') && !showCombined) return <ForbiddenState />;

  return (
    <div>
      <PageHeader
        title="Owner Command Center"
        subtitle="Live performance across your businesses"
        actions={
          <>
            <SelectInput
              label=""
              aria-label="Date range"
              value={preset}
              onChange={(e) => setPreset(e.target.value as RangePreset)}
              options={PRESETS}
            />
            {showCombined ? (
              <SelectInput
                label=""
                aria-label="Business scope"
                value={scope}
                onChange={(e) => setScope(e.target.value)}
                options={[
                  { value: 'all', label: 'All businesses' },
                  { value: 'prime', label: 'Prime only' },
                  { value: 'nest', label: 'Nest only' },
                ]}
              />
            ) : null}
          </>
        }
      />
      {showCombined ? (
        <CombinedSection scope={scope} preset={preset} />
      ) : (
        <SingleBusinessSection preset={preset} />
      )}
    </div>
  );
}

function SingleBusinessSection({ preset }: { preset: RangePreset }): JSX.Element {
  const overview = useOwnerOverview(preset);
  const revenue = useOwnerRevenue(preset);
  const leads = useOwnerLeads(preset);

  if (overview.isPending) return <CardsSkeleton count={8} />;
  if (overview.isError) {
    return (
      <ErrorState
        message={overview.error instanceof Error ? overview.error.message : 'Could not load owner data.'}
        onRetry={() => overview.refetch()}
      />
    );
  }
  const data = overview.data;
  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500" role="status">
        Last updated {formatDateTime(data.generated_at)} · {data.business.name}
        <button
          type="button"
          onClick={() => { void overview.refetch(); void revenue.refetch(); void leads.refetch(); }}
          className="ml-2 inline-flex cursor-pointer items-center gap-1 font-semibold text-slate-700 hover:text-slate-900"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Refresh
        </button>
      </p>
      <BusinessCards data={data} />
      {revenue.data ? <RevenueSection businessName={data.business.name} collected={revenue.data.summary.collected} trend={revenue.data.daily_trend} pending={revenue.data.summary.pending} overdue={revenue.data.summary.overdue} /> : null}
      {leads.data ? (
        <Card>
          <h2 className="mb-1 text-base font-bold text-slate-900">Lead conversion</h2>
          <p className="mb-3 text-xs text-slate-500">{leads.data.formulas.lead_conversion_rate}</p>
          <FunnelGrid funnel={leads.data.funnel} />
        </Card>
      ) : null}
    </div>
  );
}

function CombinedSection({ scope, preset }: { scope: string; preset: RangePreset }): JSX.Element {
  const combined = useOwnerCombined(scope, preset);
  if (combined.isPending) return <CardsSkeleton count={8} />;
  if (combined.isError) {
    return (
      <ErrorState
        message={combined.error instanceof Error ? combined.error.message : 'Could not load combined data.'}
        onRetry={() => combined.refetch()}
      />
    );
  }
  const data = combined.data;
  const totals = data.totals as Record<string, string | number>;
  const cards = [
    { label: 'Combined revenue', value: formatMoney(String(totals.collected ?? '0')) },
    { label: 'Pending', value: formatMoney(String(totals.pending ?? '0')) },
    { label: 'Overdue', value: formatMoney(String(totals.overdue ?? '0')) },
    { label: 'Payments', value: String(totals.payments ?? 0) },
    { label: 'Leads', value: String(totals.leads ?? 0) },
    { label: 'Converted', value: String(totals.converted ?? 0) },
    { label: 'Conversion', value: formatRate(Number(totals.lead_conversion_rate ?? 0)) },
  ];
  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500" role="status">
        Last updated {formatDateTime(data.generated_at)} · scope: {data.scope}
        <button
          type="button"
          onClick={() => void combined.refetch()}
          className="ml-2 inline-flex cursor-pointer items-center gap-1 font-semibold text-slate-700 hover:text-slate-900"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Refresh
        </button>
      </p>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((c) => (
          <Card key={c.label}>
            <p className="truncate text-2xl font-black tabular-nums text-slate-900">{c.value}</p>
            <p className="text-sm text-slate-500">{c.label}</p>
          </Card>
        ))}
      </div>
      {data.businesses.length === 0 ? (
        <EmptyState title="No businesses" message="No active businesses to report on yet." />
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {data.businesses.map((b) => (
            <CombinedBusinessCard key={b.business.id} item={b} />
          ))}
        </div>
      )}
    </div>
  );
}

function BusinessCards({ data }: { data: OwnerBusinessOverview }): JSX.Element {
  const kpis = [
    { label: 'Collected revenue', value: formatMoney(data.revenue.collected) },
    { label: 'Pending revenue', value: formatMoney(data.revenue.pending) },
    { label: 'Overdue', value: formatMoney(data.revenue.overdue) },
    { label: 'Active members', value: String(data.membership.active_members) },
    { label: 'Active memberships', value: String(data.membership.active_memberships) },
    { label: 'Expiring soon', value: String(data.membership.expiring_soon) },
    { label: 'Leads', value: String(data.leads.total) },
    { label: 'Conversion', value: formatRate(data.leads.lead_conversion_rate) },
    { label: "Today's visits", value: String(data.attendance_today.total) },
    { label: 'Renewals due soon', value: String(data.renewals.due_soon) },
    { label: 'Renewals overdue', value: String(data.renewals.overdue) },
    ...(data.seats
      ? [
          { label: 'Seats free', value: `${data.seats.available}/${data.seats.total}` },
        ]
      : []),
  ];
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {kpis.map((kpi) => (
        <Card key={kpi.label}>
          <p className="truncate text-2xl font-black tabular-nums text-slate-900">{kpi.value}</p>
          <p className="text-sm text-slate-500">{kpi.label}</p>
        </Card>
      ))}
    </div>
  );
}

function RevenueSection({
  businessName,
  collected,
  pending,
  overdue,
  trend,
}: {
  businessName: string;
  collected: string;
  pending: string;
  overdue: string;
  trend: Array<{ date: string; count: number; amount: string }>;
}): JSX.Element {
  const max = Math.max(1, ...trend.map((t) => Number(t.amount)));
  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-bold text-slate-900">Revenue · {businessName}</h2>
        <Link to="/payments" className="inline-flex items-center gap-1 text-sm font-semibold text-slate-600 hover:text-slate-900">
          Payments <ArrowRight className="h-4 w-4" aria-hidden />
        </Link>
      </div>
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <div><p className="text-xl font-black tabular-nums text-emerald-700">{formatMoney(collected)}</p><p className="text-xs text-slate-500">Collected</p></div>
        <div><p className="text-xl font-black tabular-nums text-amber-700">{formatMoney(pending)}</p><p className="text-xs text-slate-500">Pending</p></div>
        <div><p className="text-xl font-black tabular-nums text-rose-700">{formatMoney(overdue)}</p><p className="text-xs text-slate-500">Overdue</p></div>
      </div>
      {trend.length === 0 ? (
        <p className="py-4 text-center text-sm text-slate-500">No paid revenue in this window.</p>
      ) : (
        <div className="flex h-24 items-end gap-1" role="img" aria-label={`Daily revenue trend for ${businessName}`}>
          {trend.slice(-30).map((t) => (
            <div
              key={t.date}
              title={`${t.date}: ${formatMoney(t.amount)} (${t.count})`}
              className="min-w-0 flex-1 rounded-t bg-slate-900/80"
              style={{ height: `${Math.max(4, (Number(t.amount) / max) * 100)}%` }}
            />
          ))}
        </div>
      )}
    </Card>
  );
}

function FunnelGrid({ funnel }: { funnel: OwnerBusinessOverview['leads'] }): JSX.Element {
  const order = ['new', 'contacted', 'qualified', 'booked', 'converted', 'lost', 'spam'];
  const entries = order.filter((s) => (funnel.by_status[s] ?? 0) > 0);
  if (entries.length === 0) return <p className="py-4 text-center text-sm text-slate-500">No leads in this window.</p>;
  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {entries.map((s) => (
          <span key={s} className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1.5 text-sm ring-1 ring-slate-200">
            <StatusBadge status={s} />
            <span className="font-bold tabular-nums text-slate-900">{funnel.by_status[s]}</span>
          </span>
        ))}
      </div>
      <p className="mt-3 text-sm text-slate-600">
        Conversion <strong className="tabular-nums">{formatRate(funnel.lead_conversion_rate)}</strong>
        {' '}({funnel.converted} of {funnel.eligible} eligible) · Booking conversion{' '}
        <strong className="tabular-nums">{formatRate(funnel.booking_conversion_rate)}</strong>
      </p>
    </div>
  );
}

function CombinedBusinessCard({ item }: { item: CombinedBusinessItem }): JSX.Element {
  return (
    <Card>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="truncate text-base font-bold text-slate-900">{item.business.name}</h2>
        <Badge>{item.business.business_type}</Badge>
      </div>
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
        <div><dt className="text-xs text-slate-500">Collected</dt><dd className="font-bold tabular-nums">{formatMoney(item.revenue.collected)}</dd></div>
        <div><dt className="text-xs text-slate-500">Pending</dt><dd className="font-bold tabular-nums">{formatMoney(item.revenue.pending)}</dd></div>
        <div><dt className="text-xs text-slate-500">Overdue</dt><dd className="font-bold tabular-nums">{formatMoney(item.revenue.overdue)}</dd></div>
        <div><dt className="text-xs text-slate-500">Leads</dt><dd className="font-bold tabular-nums">{item.leads.total}</dd></div>
        <div><dt className="text-xs text-slate-500">Conversion</dt><dd className="font-bold tabular-nums">{formatRate(item.leads.lead_conversion_rate)}</dd></div>
        <div><dt className="text-xs text-slate-500">Active members</dt><dd className="font-bold tabular-nums">{item.membership.active_members}</dd></div>
        <div><dt className="text-xs text-slate-500">Visits today</dt><dd className="font-bold tabular-nums">{item.attendance_today.total}</dd></div>
        <div><dt className="text-xs text-slate-500">Renewals due</dt><dd className="font-bold tabular-nums">{item.renewals.due_soon}</dd></div>
        {item.seats ? (
          <div><dt className="text-xs text-slate-500">Seats free</dt><dd className="font-bold tabular-nums">{item.seats.available}/{item.seats.total}</dd></div>
        ) : null}
      </dl>
    </Card>
  );
}
