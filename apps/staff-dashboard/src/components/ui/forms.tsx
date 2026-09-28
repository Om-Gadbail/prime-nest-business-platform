import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react';

const CONTROL =
  'w-full rounded-xl bg-white px-3.5 text-sm text-slate-900 ring-1 ring-slate-300 placeholder:text-slate-400 focus:outline-2 focus:outline-slate-900 min-h-[44px]';

export function Field({
  label,
  error,
  hint,
  children,
  required,
}: {
  label: string;
  error?: string;
  hint?: string;
  children: ReactNode;
  required?: boolean;
}): JSX.Element {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-semibold text-slate-700">
        {label} {required ? <span aria-hidden className="text-rose-600">*</span> : null}
      </span>
      {children}
      {error ? (
        <span role="alert" className="mt-1 block text-xs font-medium text-rose-600">{error}</span>
      ) : hint ? (
        <span className="mt-1 block text-xs text-slate-500">{hint}</span>
      ) : null}
    </label>
  );
}

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
}

export function TextInput({ label, error, hint, required, id, ...rest }: InputProps): JSX.Element {
  return (
    <Field label={label} error={error} hint={hint} required={required}>
      <input id={id} aria-invalid={Boolean(error)} {...rest} className={`${CONTROL} h-11 ${rest.className ?? ''}`} />
    </Field>
  );
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  error?: string;
  hint?: string;
  options: Array<{ value: string; label: string }>;
}

export function SelectInput({ label, error, hint, required, options, ...rest }: SelectProps): JSX.Element {
  return (
    <Field label={label} error={error} hint={hint} required={required}>
      <select aria-invalid={Boolean(error)} {...rest} className={`${CONTROL} h-11 ${rest.className ?? ''}`}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </Field>
  );
}

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  error?: string;
  hint?: string;
}

export function TextArea({ label, error, hint, required, ...rest }: TextareaProps): JSX.Element {
  return (
    <Field label={label} error={error} hint={hint} required={required}>
      <textarea aria-invalid={Boolean(error)} rows={4} {...rest} className={`${CONTROL} py-3 ${rest.className ?? ''}`} />
    </Field>
  );
}

/** Paginated list controls (server-side paging). */
export function Pagination({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}): JSX.Element {
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(total, offset + limit);
  return (
    <nav aria-label="Pagination" className="flex flex-wrap items-center justify-between gap-3 pt-4">
      <p className="text-xs text-slate-500" role="status">
        Showing {from}–{to} of {total}
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onChange(offset - limit)}
          className="h-9 cursor-pointer rounded-lg px-3 text-sm font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Previous
        </button>
        <span className="text-xs font-medium text-slate-500" aria-current="page">
          Page {page} of {pages}
        </span>
        <button
          type="button"
          disabled={page >= pages}
          onClick={() => onChange(offset + limit)}
          className="h-9 cursor-pointer rounded-lg px-3 text-sm font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Next
        </button>
      </div>
    </nav>
  );
}
