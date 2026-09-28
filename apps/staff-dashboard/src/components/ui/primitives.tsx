import type { ButtonHTMLAttributes, ReactNode } from 'react';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
type Size = 'sm' | 'md' | 'lg';

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-slate-900 text-white hover:bg-slate-700 focus-visible:ring-slate-900',
  secondary: 'bg-white text-slate-800 ring-1 ring-slate-200 hover:bg-slate-50 focus-visible:ring-slate-400',
  ghost: 'bg-transparent text-slate-600 hover:bg-slate-100 focus-visible:ring-slate-400',
  danger: 'bg-rose-600 text-white hover:bg-rose-500 focus-visible:ring-rose-600',
};

const SIZES: Record<Size, string> = {
  sm: 'h-8 px-3 text-xs min-h-[32px]',
  md: 'h-10 px-4 text-sm min-h-[40px]',
  lg: 'h-12 px-6 text-sm min-h-[48px]',
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  children: ReactNode;
}

export function Button({ variant = 'primary', size = 'md', loading, children, className = '', disabled, ...rest }: Props): JSX.Element {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={`inline-flex cursor-pointer items-center justify-center gap-2 rounded-xl font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-60 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
    >
      {loading ? (
        <span aria-hidden className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
      ) : null}
      {children}
    </button>
  );
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }): JSX.Element {
  return (
    <section className={`rounded-2xl bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.06)] ring-1 ring-slate-200/70 sm:p-6 ${className}`}>
      {children}
    </section>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}): JSX.Element {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">{title}</h1>
        {subtitle ? <p className="mt-1 text-sm text-slate-500">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

const BADGE_TONES: Record<string, string> = {
  slate: 'bg-slate-100 text-slate-700 ring-slate-200',
  green: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  amber: 'bg-amber-50 text-amber-800 ring-amber-200',
  rose: 'bg-rose-50 text-rose-700 ring-rose-200',
  violet: 'bg-violet-50 text-violet-700 ring-violet-200',
  blue: 'bg-sky-50 text-sky-700 ring-sky-200',
};

export function Badge({ tone = 'slate', children }: { tone?: keyof typeof BADGE_TONES | string; children: ReactNode }): JSX.Element {
  const cls = BADGE_TONES[tone] ?? BADGE_TONES.slate;
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${cls}`}>
      {children}
    </span>
  );
}

const STATUS_TONE: Record<string, string> = {
  new: 'blue',
  contacted: 'amber',
  qualified: 'violet',
  booked: 'violet',
  converted: 'green',
  lost: 'slate',
  spam: 'rose',
  requested: 'amber',
  confirmed: 'blue',
  completed: 'green',
  cancelled: 'slate',
  no_show: 'rose',
  open: 'blue',
  in_progress: 'amber',
  active: 'green',
  inactive: 'slate',
  archived: 'slate',
};

export function StatusBadge({ status }: { status: string }): JSX.Element {
  const tone = STATUS_TONE[status.toLowerCase()] ?? 'slate';
  return <Badge tone={tone}>{status.replace(/_/g, ' ')}</Badge>;
}

const PRIORITY_TONE: Record<string, string> = {
  low: 'slate',
  medium: 'blue',
  high: 'amber',
  urgent: 'rose',
};

export function PriorityBadge({ priority }: { priority: string }): JSX.Element {
  return <Badge tone={PRIORITY_TONE[priority.toLowerCase()] ?? 'slate'}>{priority}</Badge>;
}
