import { useRef, useState } from 'react';
import { MessageCircle, Send, X } from 'lucide-react';

/**
 * Reusable website AI receptionist widget (Blocks 8-12).
 *
 * Drop-in for the Prime and Nest websites (or any future business site):
 * the business is resolved server-side from `businessSlug` — the Gemini API
 * key never reaches the browser. Slots, plans, location and booking status
 * always come from backend tools, never invented.
 *
 * ```tsx
 * <WebsiteChat apiBaseUrl="http://localhost:8000" businessSlug="prime"
 *              businessName="Prime Fitness" accent="#16a34a" />
 * ```
 */

interface ChatMessage {
  role: 'visitor' | 'assistant';
  text: string;
}

const QUICK_ACTIONS = [
  'What are your timings?',
  'Where are you located?',
  'What memberships do you have?',
  'What slots are available tomorrow?',
];

const ACTION_BUTTONS = ['Book a Visit', 'View Memberships', 'Get Directions', 'Talk to Staff'];

export function WebsiteChat({
  apiBaseUrl,
  businessSlug,
  businessName,
  accent = '#16a34a',
}: {
  apiBaseUrl: string;
  businessSlug: string;
  businessName: string;
  accent?: string;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'assistant', text: `Hi! I'm the ${businessName} assistant. Ask about timings, location, memberships or bookings.` },
  ]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [visitorKey] = useState(() => `web-${Date.now().toString(36)}`);
  const bottomRef = useRef<HTMLDivElement>(null);

  const scrollDown = (): void => {
    window.setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), 50);
  };

  const send = async (text: string): Promise<void> => {
    const clean = text.trim();
    if (!clean || busy) return;
    setMessages((m) => [...m, { role: 'visitor', text: clean }]);
    setInput('');
    setBusy(true);
    scrollDown();
    try {
      const resp = await fetch(
        `${apiBaseUrl.replace(/\/$/, '')}/api/v1/public/${businessSlug}/ai/chat`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: clean, visitor_key: visitorKey }),
        },
      );
      const data = (await resp.json()) as { reply?: string };
      setMessages((m) => [
        ...m,
        { role: 'assistant', text: data.reply ?? 'Sorry — please try again or contact the team.' },
      ]);
    } catch {
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          text: "I'm having trouble right now. Please call the team or leave an enquiry and staff will respond.",
        },
      ]);
    } finally {
      setBusy(false);
      scrollDown();
    }
  };

  const action = (label: string): void => {
    if (label === 'View Memberships') void send('What memberships do you have?');
    else if (label === 'Get Directions') void send('Where are you located?');
    else if (label === 'Book a Visit') void send('I want to book a visit. What slots are available tomorrow?');
    else void send('I would like to talk to staff.');
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`Chat with ${businessName}`}
        className="fixed bottom-4 right-4 z-50 flex h-14 w-14 cursor-pointer items-center justify-center rounded-full text-white shadow-lg"
        style={{ backgroundColor: accent }}
      >
        <MessageCircle className="h-6 w-6" aria-hidden />
      </button>
    );
  }

  return (
    <section
      aria-label={`${businessName} AI assistant`}
      className="fixed bottom-4 right-4 z-50 flex max-h-[80vh] w-[calc(100vw-2rem)] max-w-sm flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200"
    >
      <header className="flex items-center gap-2 px-4 py-3 text-white" style={{ backgroundColor: accent }}>
        <MessageCircle className="h-5 w-5" aria-hidden />
        <p className="min-w-0 flex-1 truncate text-sm font-bold">{businessName} AI Assistant</p>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Close chat"
          className="cursor-pointer rounded p-1 hover:bg-white/20"
        >
          <X className="h-5 w-5" aria-hidden />
        </button>
      </header>
      <div className="max-h-[50vh] min-h-[240px] flex-1 space-y-2 overflow-y-auto p-3" aria-live="polite">
        {messages.map((m, i) => (
          <p
            key={i}
            className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm ${
              m.role === 'visitor'
                ? 'ml-auto text-white'
                : 'bg-slate-100 text-slate-900 ring-1 ring-slate-200'
            }`}
            style={m.role === 'visitor' ? { backgroundColor: accent } : undefined}
          >
            {m.text}
          </p>
        ))}
        {busy ? <p className="text-xs text-slate-500">Typing…</p> : null}
        <div ref={bottomRef} />
      </div>
      <div className="space-y-2 border-t border-slate-100 p-3">
        <div className="flex flex-wrap gap-1.5">
          {ACTION_BUTTONS.map((b) => (
            <button
              key={b}
              type="button"
              onClick={() => action(b)}
              className="cursor-pointer rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700 ring-1 ring-slate-200 hover:bg-slate-200"
            >
              {b}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {QUICK_ACTIONS.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => void send(q)}
              className="cursor-pointer rounded-full px-2.5 py-1 text-xs font-semibold text-white"
              style={{ backgroundColor: accent }}
            >
              {q}
            </button>
          ))}
        </div>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void send(input);
          }}
        >
          <label htmlFor="website-chat-input" className="sr-only">
            Type your message
          </label>
          <input
            id="website-chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about timings, plans…"
            className="min-w-0 flex-1 rounded-full border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2"
            autoComplete="off"
          />
          <button
            type="submit"
            disabled={!input.trim() || busy}
            aria-label="Send message"
            className="flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-full text-white disabled:opacity-50"
            style={{ backgroundColor: accent }}
          >
            <Send className="h-4 w-4" aria-hidden />
          </button>
        </form>
      </div>
    </section>
  );
}
