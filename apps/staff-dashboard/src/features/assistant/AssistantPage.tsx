import { useState } from 'react';
import { Bot, Check, Send, X } from 'lucide-react';
import { useSession } from '../../lib/auth';
import { useAssistant, useDecideRecommendation, useRecommendations } from './hooks';
import { Badge, Button, Card, PageHeader } from '../../components/ui/primitives';
import { CardsSkeleton, EmptyState, ErrorState, ForbiddenState } from '../../components/ui/states';
import { TextArea } from '../../components/ui/forms';

interface ChatTurn {
  role: 'user' | 'assistant';
  text: string;
}

/** Owner/staff AI assistant: real business data through controlled tools. */
export function AssistantPage(): JSX.Element {
  const { can } = useSession();
  if (!can('ai.assist')) return <ForbiddenState />;

  return (
    <div>
      <PageHeader title="AI Assistant" subtitle="Answers from real business data — never invented" />
      <div className="grid gap-4 xl:grid-cols-2">
        <ChatCard />
        <RecommendationsCard />
      </div>
    </div>
  );
}

const SUGGESTIONS = [
  'What happened today?',
  'Which memberships expire this week?',
  'Which leads need follow-up?',
  'Show me revenue for this month.',
];

function ChatCard(): JSX.Element {
  const chat = useAssistant();
  const [input, setInput] = useState('');
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const ask = (message: string): void => {
    const clean = message.trim();
    if (!clean || chat.isPending) return;
    setTurns((t) => [...t, { role: 'user', text: clean }]);
    setInput('');
    chat.mutate(clean, {
      onSuccess: (res) => setTurns((t) => [...t, { role: 'assistant', text: res.reply }]),
      onError: (err) =>
        setTurns((t) => [
          ...t,
          { role: 'assistant', text: err instanceof Error ? err.message : 'Assistant unavailable.' },
        ]),
    });
  };
  return (
    <Card>
      <h2 className="mb-3 flex items-center gap-2 text-base font-bold text-slate-900">
        <Bot className="h-5 w-5" aria-hidden /> Ask about your business
      </h2>
      <div className="mb-3 max-h-[320px] space-y-2 overflow-y-auto" aria-live="polite">
        {turns.length === 0 ? (
          <p className="py-6 text-center text-sm text-slate-500">
            Try: “What happened today?” or “Which leads need follow-up?”
          </p>
        ) : (
          turns.map((t, i) => (
            <p
              key={i}
              className={`max-w-[90%] rounded-2xl px-3 py-2 text-sm ${
                t.role === 'user'
                  ? 'ml-auto bg-slate-900 text-white'
                  : 'bg-slate-100 text-slate-900 ring-1 ring-slate-200'
              }`}
            >
              {t.text}
            </p>
          ))
        )}
        {chat.isPending ? <p className="text-sm text-slate-500">Thinking…</p> : null}
      </div>
      <div className="mb-3 flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => ask(s)}
            className="cursor-pointer rounded-full bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200 hover:bg-slate-200"
          >
            {s}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <TextArea
          label="Ask the assistant"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          rows={2}
          placeholder="Ask about leads, revenue, renewals…"
        />
        <Button onClick={() => ask(input)} loading={chat.isPending}>
          <Send className="h-4 w-4" aria-hidden /> Ask
        </Button>
      </div>
    </Card>
  );
}

function RecommendationsCard(): JSX.Element {
  const { can } = useSession();
  const recs = useRecommendations();
  const decide = useDecideRecommendation();
  if (!can('ai.read')) return <></>;
  if (recs.isPending) return <CardsSkeleton count={4} />;
  if (recs.isError) {
    return (
      <ErrorState
        message={recs.error instanceof Error ? recs.error.message : 'Could not load recommendations.'}
        onRetry={() => recs.refetch()}
      />
    );
  }
  if (recs.data.items.length === 0) {
    return <EmptyState title="No recommendations" message="Automation and AI signals appear here for review." />;
  }
  const manage = can('ai.manage');
  return (
    <Card>
      <h2 className="mb-3 text-base font-bold text-slate-900">Recommendations ({recs.data.total})</h2>
      <ul className="space-y-3">
        {recs.data.items.map((r) => (
          <li key={r.id} className="rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200">
            <p className="flex flex-wrap items-center gap-2 text-sm font-bold text-slate-900">
              {r.title}
              <Badge>{r.status}</Badge>
              <Badge>{r.risk_level} risk</Badge>
            </p>
            <p className="mt-1 text-sm text-slate-600">{r.reason}</p>
            <p className="mt-1 text-xs text-slate-500">Suggested: {r.suggested_action}</p>
            {manage && r.status === 'pending' ? (
              <p className="mt-2 flex gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  loading={decide.isPending}
                  onClick={() => decide.mutate({ id: r.id, decision: 'approved' })}
                >
                  <Check className="h-4 w-4" aria-hidden /> Approve
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  loading={decide.isPending}
                  onClick={() => decide.mutate({ id: r.id, decision: 'rejected' })}
                >
                  <X className="h-4 w-4" aria-hidden /> Reject
                </Button>
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </Card>
  );
}
