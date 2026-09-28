import type { ReactNode } from 'react';
import { AlertTriangle, Inbox, SearchX } from 'lucide-react';
import { Button } from './primitives';

/** Loading skeletons (table + cards). */
export function TableSkeleton({ rows = 5, cols = 4 }: { rows?: number; cols?: number }): JSX.Element {
  return (
    <div role="status" aria-label="Loading" className="animate-pulse space-y-3">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="grid gap-3" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
          {Array.from({ length: cols }).map((_, c) => (
            <div key={c} className="h-5 rounded-md bg-slate-200" />
          ))}
        </div>
      ))}
    </div>
  );
}

export function CardsSkeleton({ count = 4 }: { count?: number }): JSX.Element {
  return (
    <div role="status" aria-label="Loading" className="grid animate-pulse gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="h-28 rounded-2xl bg-slate-200" />
      ))}
    </div>
  );
}

/** Empty state with icon + action. */
export function EmptyState({
  icon,
  title,
  message,
  action,
}: {
  icon?: ReactNode;
  title: string;
  message?: string;
  action?: ReactNode;
}): JSX.Element {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl bg-white px-6 py-14 text-center ring-1 ring-slate-200/70">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-400">
        {icon ?? <Inbox className="h-6 w-6" aria-hidden />}
      </div>
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      {message ? <p className="mt-1 max-w-sm text-sm text-slate-500">{message}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function NoResults({ onClear }: { onClear?: () => void }): JSX.Element {
  return (
    <EmptyState
      icon={<SearchX className="h-6 w-6" aria-hidden />}
      title="No results"
      message="Try adjusting the search or clearing the filters."
      action={onClear ? <Button variant="secondary" size="sm" onClick={onClear}>Clear filters</Button> : undefined}
    />
  );
}

/** Error state with retry. */
export function ErrorState({
  title = 'Something went wrong',
  message,
  onRetry,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
}): JSX.Element {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl bg-white px-6 py-14 text-center ring-1 ring-slate-200/70">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-rose-50 text-rose-500">
        <AlertTriangle className="h-6 w-6" aria-hidden />
      </div>
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      {message ? <p className="mt-1 max-w-sm text-sm text-slate-500">{message}</p> : null}
      {onRetry ? (
        <div className="mt-4">
          <Button variant="secondary" size="sm" onClick={onRetry}>Try again</Button>
        </div>
      ) : null}
    </div>
  );
}

/** Permission-denied state (backend enforces; this is UX only). */
export function ForbiddenState({ message }: { message?: string }): JSX.Element {
  return (
    <EmptyState
      title="Not allowed"
      message={message ?? 'Your role does not include access to this area. Contact an administrator if you need it.'}
    />
  );
}
