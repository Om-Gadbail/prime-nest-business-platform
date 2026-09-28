import { Link, useParams } from 'react-router-dom';
import { useSession } from '../../lib/auth';
import { useMemberProfile } from './hooks';
import { Badge, Button, Card, PageHeader, StatusBadge } from '../../components/ui/primitives';
import { CardsSkeleton, ErrorState } from '../../components/ui/states';
import { formatDate, formatDateTime, formatMoney } from '../../lib/list';

/**
 * Member 360°: identity, current membership, history, payments,
 * attendance, renewals, and seat — with links across records.
 */
export function MemberDetailPage(): JSX.Element {
  const { id = '' } = useParams();
  const { can } = useSession();
  const profile = useMemberProfile(id);

  if (profile.isPending) return <CardsSkeleton />;
  if (profile.isError) {
    return (
      <ErrorState
        message={profile.error instanceof Error ? profile.error.message : 'Could not load the member.'}
        onRetry={() => profile.refetch()}
      />
    );
  }
  const data = profile.data;
  const m = data.member;
  return (
    <div>
      <PageHeader
        title={m.display_name || 'Member'}
        subtitle={[m.phone, m.email].filter(Boolean).join(' · ') || 'No contact details'}
        actions={
          can('members.update') ? (
            <Link to="/members"><Button size="sm" variant="secondary">Back to members</Button></Link>
          ) : undefined
        }
      />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <h2 className="mb-3 text-base font-bold text-slate-900">Profile</h2>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div><dt className="text-xs text-slate-500">Status</dt><dd><StatusBadge status={m.status} /></dd></div>
            <div><dt className="text-xs text-slate-500">Source</dt><dd className="font-medium">{m.source}</dd></div>
            <div><dt className="text-xs text-slate-500">Emergency contact</dt><dd className="font-medium">{m.emergency_contact_name || '—'}</dd></div>
            <div><dt className="text-xs text-slate-500">Emergency phone</dt><dd className="font-medium">{m.emergency_contact_phone || '—'}</dd></div>
            <div className="col-span-2"><dt className="text-xs text-slate-500">Seat preference</dt><dd className="font-medium">{m.seat_preference || '—'}</dd></div>
            {m.notes ? <div className="col-span-2"><dt className="text-xs text-slate-500">Notes</dt><dd className="font-medium">{m.notes}</dd></div> : null}
          </dl>
        </Card>
        <Card>
          <h2 className="mb-3 text-base font-bold text-slate-900">Current membership</h2>
          {data.current_membership ? (
            <div className="text-sm">
              <p className="font-semibold">{data.current_membership.plan_name_snapshot || 'Custom plan'}</p>
              <p className="text-slate-500">{formatDate(data.current_membership.start_date)} → {formatDate(data.current_membership.end_date)}</p>
              <p className="mt-1 font-bold tabular-nums">{formatMoney(data.current_membership.final_amount, data.current_membership.currency)}</p>
              <div className="mt-2 flex gap-2">
                <StatusBadge status={data.current_membership.status} />
                <Badge>{data.current_membership.payment_state}</Badge>
              </div>
              <Link to={`/memberships?member=${m.id}`} className="mt-3 inline-block text-sm font-semibold text-slate-700 hover:text-slate-900">
                All memberships →
              </Link>
            </div>
          ) : (
            <p className="py-4 text-center text-sm text-slate-500">No active membership.</p>
          )}
          {data.active_seat_allocation ? (
            <div className="mt-4 border-t border-slate-100 pt-3 text-sm">
              <p className="text-xs text-slate-500">Active seat allocation</p>
              <Link to="/seats" className="font-semibold text-slate-800 hover:text-slate-900">
                View seats →
              </Link>
            </div>
          ) : null}
        </Card>
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-bold text-slate-900">Payments</h2>
            <Link to={`/payments?member=${m.id}`} className="text-sm font-semibold text-slate-600 hover:text-slate-900">View all →</Link>
          </div>
          {data.payments.length === 0 ? (
            <p className="py-4 text-center text-sm text-slate-500">No payments yet.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.payments.slice(0, 5).map((p) => (
                <li key={p.id} className="flex items-center justify-between gap-2 py-2 text-sm">
                  <span className="font-semibold tabular-nums">{formatMoney(p.amount, p.currency)}</span>
                  <StatusBadge status={p.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-bold text-slate-900">Recent visits</h2>
            <Link to={`/attendance?member=${m.id}`} className="text-sm font-semibold text-slate-600 hover:text-slate-900">View all →</Link>
          </div>
          {data.attendance.length === 0 ? (
            <p className="py-4 text-center text-sm text-slate-500">No visits yet.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.attendance.slice(0, 5).map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-2 py-2 text-sm">
                  <span>{formatDate(a.attendance_date)}</span>
                  <span className="text-xs text-slate-500">{a.checked_out_at ? `out ${formatDateTime(a.checked_out_at)}` : 'checked in'}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      {data.renewals.length > 0 ? (
        <Card className="mt-4">
          <h2 className="mb-3 text-base font-bold text-slate-900">Renewals</h2>
          <ul className="divide-y divide-slate-100">
            {data.renewals.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                <span className="font-medium">Due {formatDate(r.due_date)}</span>
                <StatusBadge status={r.status} />
                <span className="ml-auto font-semibold tabular-nums">{formatMoney(r.renewal_amount, r.currency)}</span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
