import { useState } from 'react';
import { Plus } from 'lucide-react';
import { useSession } from '../../lib/auth';
import { useCreateReferral, useCrossSell, useFunnel, useReferrals, useSources } from './hooks';
import { Badge, Button, Card, PageHeader } from '../../components/ui/primitives';
import { CardsSkeleton, EmptyState, ErrorState, ForbiddenState } from '../../components/ui/states';
import { TextInput } from '../../components/ui/forms';

/** Growth: source → lead → conversion → revenue, referrals, cross-sell. */
export function GrowthPage(): JSX.Element {
  const { can } = useSession();
  if (!can('growth.read')) return <ForbiddenState />;

  return (
    <div>
      <PageHeader title="Growth" subtitle="Where customers come from — and what converts" />
      <div className="grid gap-4 xl:grid-cols-2">
        <FunnelCard />
        <ReferralsCard />
        <CrossSellCard />
        <SourcesCard />
      </div>
    </div>
  );
}

function SourcesCard(): JSX.Element {
  const sources = useSources();
  if (sources.isPending) return <CardsSkeleton count={3} />;
  if (sources.isError) {
    return (
      <ErrorState
        message={sources.error instanceof Error ? sources.error.message : 'Could not load sources.'}
        onRetry={() => sources.refetch()}
      />
    );
  }
  return (
    <Card>
      <h2 className="mb-3 text-base font-bold text-slate-900">Sources</h2>
      <div className="flex flex-wrap gap-2">
        {sources.data.items.map((s) => (
          <Badge key={s.id}>{s.name}</Badge>
        ))}
      </div>
    </Card>
  );
}

function FunnelCard(): JSX.Element {
  const funnel = useFunnel();
  if (funnel.isPending) return <CardsSkeleton count={4} />;
  if (funnel.isError) {
    return (
      <ErrorState
        message={funnel.error instanceof Error ? funnel.error.message : 'Could not load the funnel.'}
        onRetry={() => funnel.refetch()}
      />
    );
  }
  const entries = Object.entries(funnel.data.funnel);
  if (entries.length === 0) {
    return <EmptyState title="No attribution yet" message="Leads with recorded sources appear here." />;
  }
  const max = Math.max(1, ...entries.map(([, v]) => v.leads));
  return (
    <Card>
      <h2 className="mb-3 text-base font-bold text-slate-900">Attribution funnel</h2>
      <ul className="space-y-2">
        {entries.map(([source, v]) => (
          <li key={source}>
            <p className="flex justify-between text-sm">
              <span className="font-semibold text-slate-900">{source}</span>
              <span className="tabular-nums text-slate-600">
                {v.leads} leads · {v.converted} converted
              </span>
            </p>
            <div className="mt-1 h-2 rounded-full bg-slate-100" role="img" aria-label={`${source}: ${v.leads} leads`}>
              <div className="h-2 rounded-full bg-slate-900" style={{ width: `${(v.leads / max) * 100}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function ReferralsCard(): JSX.Element {
  const { can } = useSession();
  const referrals = useReferrals();
  const create = useCreateReferral();
  const [referrer, setReferrer] = useState('');
  const [referred, setReferred] = useState('');
  if (referrals.isPending) return <CardsSkeleton count={4} />;
  if (referrals.isError) {
    return (
      <ErrorState
        message={referrals.error instanceof Error ? referrals.error.message : 'Could not load referrals.'}
        onRetry={() => referrals.refetch()}
      />
    );
  }
  return (
    <Card>
      <h2 className="mb-3 text-base font-bold text-slate-900">Referrals ({referrals.data.total})</h2>
      {referrals.data.items.length === 0 ? (
        <p className="mb-3 py-2 text-center text-sm text-slate-500">No referrals yet.</p>
      ) : (
        <ul className="mb-3 divide-y divide-slate-100">
          {referrals.data.items.slice(0, 10).map((r) => (
            <li key={r.id} className="flex items-center gap-2 py-2 text-sm">
              <span className="min-w-0 flex-1 truncate text-slate-900">
                {r.referrer_name} → {r.referred_name}
              </span>
              <Badge>{r.status}</Badge>
            </li>
          ))}
        </ul>
      )}
      {can('growth.manage') ? (
        <div className="grid gap-2 sm:grid-cols-2">
          <TextInput label="Referrer name" value={referrer} onChange={(e) => setReferrer(e.target.value)} placeholder="Existing member" />
          <TextInput label="Referred name" value={referred} onChange={(e) => setReferred(e.target.value)} placeholder="New lead" />
          <div className="sm:col-span-2">
            <Button
              size="sm"
              loading={create.isPending}
              disabled={!referrer.trim() || !referred.trim()}
              onClick={() => {
                create.mutate({ referrer_name: referrer.trim(), referred_name: referred.trim() });
                setReferrer('');
                setReferred('');
              }}
            >
              <Plus className="h-4 w-4" aria-hidden /> Add referral
            </Button>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

function CrossSellCard(): JSX.Element {
  const xsell = useCrossSell();
  if (xsell.isPending) return <CardsSkeleton count={3} />;
  if (xsell.isError) {
    return (
      <ErrorState
        message={xsell.error instanceof Error ? xsell.error.message : 'Could not load cross-sell.'}
        onRetry={() => xsell.refetch()}
      />
    );
  }
  if (xsell.data.items.length === 0) {
    return <EmptyState title="No cross-sell opportunities" message="Prime ↔ Nest opportunities appear here when eligible." />;
  }
  return (
    <Card>
      <h2 className="mb-3 text-base font-bold text-slate-900">Cross-sell ({xsell.data.total})</h2>
      <ul className="divide-y divide-slate-100">
        {xsell.data.items.slice(0, 10).map((o) => (
          <li key={o.id} className="py-2 text-sm">
            <p className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 flex-1 truncate font-semibold text-slate-900">{o.offer || 'Opportunity'}</span>
              <Badge>{o.status}</Badge>
              {o.consent ? <Badge>consented</Badge> : null}
            </p>
          </li>
        ))}
      </ul>
    </Card>
  );
}
