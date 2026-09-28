import { Link } from 'react-router-dom';
import { ArrowRight, Bell, CalendarClock, CheckSquare, UserPlus } from 'lucide-react';
import { useSession } from '../../lib/auth';
import { useOverview } from './hooks';
import { Badge, Button, Card, PageHeader } from '../../components/ui/primitives';
import { CardsSkeleton, ErrorState } from '../../components/ui/states';
import { formatDateTime } from '../../lib/list';

/** Dashboard home: today's numbers, assigned work, recent activity, quick actions. */
export function OverviewPage(): JSX.Element {
  const { can, preset } = useSession();
  const overview = useOverview();

  if (overview.isPending) return <CardsSkeleton />;
  if (overview.isError) {
    return (
      <ErrorState
        message={overview.error instanceof Error ? overview.error.message : 'Could not load the overview.'}
        onRetry={() => overview.refetch()}
      />
    );
  }

  const data = overview.data;
  const kpis = [
    { label: 'New leads', value: data.leads.new, to: '/leads?status=new', icon: UserPlus },
    { label: 'Follow-ups due', value: data.leads.follow_ups_due, to: '/leads', icon: Bell },
    { label: 'Booking requests', value: data.bookings.requested, to: '/bookings?status=requested', icon: CalendarClock },
    { label: 'My overdue tasks', value: data.tasks.mine_overdue, to: '/tasks?overdue=true', icon: CheckSquare },
  ];

  return (
    <div>
      <PageHeader
        title="Today's overview"
        subtitle={`Generated ${formatDateTime(data.generated_at)}`}
        actions={
          <>
            {can('leads.create') ? (
              <Link to="/leads?new=1"><Button size="sm">New lead</Button></Link>
            ) : null}
            {can('tasks.create') ? (
              <Link to="/tasks?new=1"><Button size="sm" variant="secondary">New task</Button></Link>
            ) : null}
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {kpis.map((kpi) => (
          <Link key={kpi.label} to={kpi.to} className="rounded-2xl focus-visible:outline-2 focus-visible:outline-slate-900">
            <Card className="flex items-center gap-4 transition hover:shadow-md">
              <span
                aria-hidden
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-white"
                style={{ backgroundColor: preset.accent }}
              >
                <kpi.icon className="h-5 w-5" />
              </span>
              <span>
                <span className="block text-2xl font-black tabular-nums text-slate-900">{kpi.value}</span>
                <span className="block text-sm font-medium text-slate-500">{kpi.label}</span>
              </span>
            </Card>
          </Link>
        ))}
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-bold text-slate-900">Recent leads</h2>
            <Link to="/leads" className="inline-flex items-center gap-1 text-sm font-semibold text-slate-600 hover:text-slate-900">
              View all <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          </div>
          {data.recent_leads.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-500">No leads yet.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.recent_leads.map((lead) => (
                <li key={lead.id}>
                  <Link to={`/leads/${lead.id}`} className="flex items-center justify-between gap-3 py-2.5">
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-semibold text-slate-900">{lead.display_name || 'Unnamed lead'}</span>
                      <span className="block truncate text-xs text-slate-500">{lead.source} · {formatDateTime(lead.created_at)}</span>
                    </span>
                    <Badge>{lead.status}</Badge>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-bold text-slate-900">Recent activity</h2>
            <Link to="/activity" className="inline-flex items-center gap-1 text-sm font-semibold text-slate-600 hover:text-slate-900">
              View all <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          </div>
          {data.recent_activity.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-500">No activity yet.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.recent_activity.map((a) => (
                <li key={a.id} className="py-2.5">
                  <p className="truncate text-sm font-medium text-slate-800">
                    {a.activity_type.replace(/_/g, ' ')}
                  </p>
                  <p className="truncate text-xs text-slate-500">{a.note} · {formatDateTime(a.created_at)}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <Card className="text-center">
          <p className="text-2xl font-black text-slate-900">{data.tasks.mine_open}</p>
          <p className="text-sm text-slate-500">My open tasks</p>
          <Link to="/tasks?mine=1" className="mt-2 inline-block text-sm font-semibold text-slate-700 hover:text-slate-900">Open my tasks →</Link>
        </Card>
        <Card className="text-center">
          <p className="text-2xl font-black text-slate-900">{data.notifications.unread}</p>
          <p className="text-sm text-slate-500">Unread notifications</p>
          <Link to="/notifications" className="mt-2 inline-block text-sm font-semibold text-slate-700 hover:text-slate-900">Open inbox →</Link>
        </Card>
        <Card className="text-center">
          <p className="text-2xl font-black text-slate-900">{data.leads.created_today + data.bookings.created_today}</p>
          <p className="text-sm text-slate-500">Enquiries today</p>
        </Card>
      </div>
    </div>
  );
}
