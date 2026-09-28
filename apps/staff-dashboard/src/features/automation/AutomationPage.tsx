import { Play, RefreshCw, Sparkles } from 'lucide-react';
import { useSession } from '../../lib/auth';
import { useAutoExecutions, useAutoRules, useBrief, useRunScheduler, useSeedDefaults } from './hooks';
import { Badge, Button, Card, PageHeader, StatusBadge } from '../../components/ui/primitives';
import { CardsSkeleton, EmptyState, ErrorState, ForbiddenState } from '../../components/ui/states';

/** Automation Engine: rules, executions, daily brief, scheduler controls. */
export function AutomationPage(): JSX.Element {
  const { can } = useSession();
  if (!can('automation.read')) return <ForbiddenState />;
  const manage = can('automation.manage');

  return (
    <div>
      <PageHeader
        title="Automation"
        subtitle="Event-driven workflows across the business"
        actions={manage ? <SeedButton /> : undefined}
      />
      <div className="space-y-4">
        <BriefCard />
        <RulesCard />
        <ExecutionsCard />
        {manage ? <SchedulerCard /> : null}
      </div>
    </div>
  );
}

function SeedButton(): JSX.Element {
  const seed = useSeedDefaults();
  return (
    <Button variant="secondary" size="sm" loading={seed.isPending} onClick={() => seed.mutate()}>
      <Sparkles className="h-4 w-4" aria-hidden /> Seed defaults
    </Button>
  );
}

function BriefCard(): JSX.Element {
  const { can } = useSession();
  const brief = useBrief();
  if (!can('reports.read')) return <></>;
  if (brief.isPending) return <CardsSkeleton count={3} />;
  if (brief.isError) {
    return (
      <ErrorState
        message={brief.error instanceof Error ? brief.error.message : 'Could not load the daily brief.'}
        onRetry={() => brief.refetch()}
      />
    );
  }
  const b = brief.data;
  return (
    <Card>
      <h2 className="mb-1 text-base font-bold text-slate-900">Daily brief · {b.report_date}</h2>
      <p className="mb-3 text-xs text-slate-500">Yesterday → today → trend → exceptions → actions</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <BriefList title="Yesterday" entries={b.yesterday} />
        <BriefList title="Today" entries={b.today} />
        <BriefList title="Trend" entries={b.trend} />
      </div>
      {b.exceptions.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {b.exceptions.map((e, i) => (
            <Badge key={i}>{String(e.type ?? 'alert')} · {String(e.count ?? '')}</Badge>
          ))}
        </div>
      ) : null}
      <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-700">
        {b.recommended_actions.map((a, i) => (
          <li key={i}>{a}</li>
        ))}
      </ul>
    </Card>
  );
}

function BriefList({ title, entries }: { title: string; entries: Record<string, unknown> }): JSX.Element {
  return (
    <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
      <p className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">{title}</p>
      <dl className="space-y-1 text-sm">
        {Object.entries(entries).slice(0, 6).map(([k, v]) => (
          <div key={k} className="flex items-center justify-between gap-2">
            <dt className="truncate text-slate-500">{k.replace(/_/g, ' ')}</dt>
            <dd className="font-bold tabular-nums text-slate-900">{typeof v === 'object' ? '—' : String(v)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function RulesCard(): JSX.Element {
  const rules = useAutoRules();
  if (rules.isPending) return <CardsSkeleton count={4} />;
  if (rules.isError) {
    return (
      <ErrorState
        message={rules.error instanceof Error ? rules.error.message : 'Could not load rules.'}
        onRetry={() => rules.refetch()}
      />
    );
  }
  if (rules.data.items.length === 0) {
    return <EmptyState title="No automation rules" message="Seed defaults to enable lead, booking and renewal workflows." />;
  }
  return (
    <Card>
      <h2 className="mb-3 text-base font-bold text-slate-900">Rules ({rules.data.total})</h2>
      <ul className="divide-y divide-slate-100">
        {rules.data.items.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center gap-2 py-2.5">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold text-slate-900">{r.name}</span>
              <span className="block truncate font-mono text-xs text-slate-500">{r.event_type}</span>
            </span>
            <Badge>{r.is_active ? 'active' : 'paused'}</Badge>
            <Badge>{r.actions.length} action{r.actions.length === 1 ? '' : 's'}</Badge>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function ExecutionsCard(): JSX.Element {
  const execs = useAutoExecutions();
  if (execs.isPending) return <CardsSkeleton count={4} />;
  if (execs.isError) {
    return (
      <ErrorState
        message={execs.error instanceof Error ? execs.error.message : 'Could not load executions.'}
        onRetry={() => execs.refetch()}
      />
    );
  }
  if (execs.data.items.length === 0) {
    return <EmptyState title="No executions yet" message="Executions appear here when events trigger rules." />;
  }
  return (
    <Card>
      <h2 className="mb-3 text-base font-bold text-slate-900">Recent executions</h2>
      <ul className="divide-y divide-slate-100">
        {execs.data.items.slice(0, 20).map((e) => (
          <li key={e.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
            <StatusBadge status={e.status} />
            <span className="min-w-0 flex-1 truncate font-mono text-xs text-slate-500">
              {e.event_type} · attempt {e.attempt_count}
            </span>
            {e.error ? <span className="w-full truncate text-xs text-rose-600">{e.error}</span> : null}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function SchedulerCard(): JSX.Element {
  const run = useRunScheduler();
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-bold text-slate-900">Scheduler</h2>
          <p className="text-xs text-slate-500">Retry failed executions and run due follow-ups (bounded, idempotent).</p>
        </div>
        <Button size="sm" loading={run.isPending} onClick={() => run.mutate()}>
          <Play className="h-4 w-4" aria-hidden /> Run due
        </Button>
        {run.data ? (
          <span className="inline-flex items-center gap-1 text-xs text-slate-500" role="status">
            <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Ran {run.data.ran}
          </span>
        ) : null}
      </div>
    </Card>
  );
}
