import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useLocation, useNavigate } from 'react-router-dom';
import { z } from 'zod';
import { getConfiguredSlug, presetForSlug } from '../../config/business';
import { useSession } from '../../lib/auth';
import { Button, Card } from '../../components/ui/primitives';
import { TextInput } from '../../components/ui/forms';

const schema = z.object({
  email: z.string().email('Enter a valid email.'),
  password: z.string().min(1, 'Password is required.'),
});

type FormValues = z.infer<typeof schema>;

/** Staff sign-in (access token stays in memory; refresh via HttpOnly cookie). */
export function LoginPage(): JSX.Element {
  const { login, status, authError, preset } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const [pending, setPending] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const activePreset = presetForSlug(getConfiguredSlug());
  const from = (location.state as { from?: string } | null)?.from ?? '/';

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>();

  if (status === 'authenticated') {
    navigate(from, { replace: true });
  }

  const onSubmit = handleSubmit(async (values) => {
    setPending(true);
    setFormError(null);
    try {
      await login(values.email.trim(), values.password, getConfiguredSlug());
      navigate(from, { replace: true });
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Sign in failed.');
    } finally {
      setPending(false);
    }
  });

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-3">
          <span
            aria-hidden
            className="flex h-12 w-12 items-center justify-center rounded-2xl text-base font-black text-white"
            style={{ backgroundColor: (preset ?? activePreset).accent }}
          >
            {(preset ?? activePreset).initials}
          </span>
          <div>
            <h1 className="text-xl font-bold text-white">{(preset ?? activePreset).name}</h1>
            <p className="text-sm text-slate-400">Staff dashboard</p>
          </div>
        </div>
        <Card>
          <h2 className="text-lg font-bold text-slate-900">Sign in</h2>
          <p className="mb-5 mt-1 text-sm text-slate-500">Use your staff account to continue.</p>
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <TextInput
              label="Email"
              type="email"
              autoComplete="username"
              placeholder="you@example.com"
              error={errors.email?.message}
              {...register('email', {
                validate: (v) => {
                  const parsed = schema.shape.email.safeParse(v);
                  return parsed.success ? true : parsed.error.issues[0]?.message ?? 'Invalid email.';
                },
              })}
            />
            <TextInput
              label="Password"
              type="password"
              autoComplete="current-password"
              placeholder="••••••••"
              error={errors.password?.message}
              {...register('password', { required: 'Password is required.' })}
            />
            {formError ?? authError ? (
              <p role="alert" className="rounded-xl bg-rose-50 px-3.5 py-2.5 text-sm font-medium text-rose-700 ring-1 ring-rose-200">
                {formError ?? authError}
              </p>
            ) : null}
            <Button type="submit" loading={pending} className="w-full" size="lg">
              Sign in
            </Button>
          </form>
        </Card>
        <p className="mt-4 text-center text-xs text-slate-500">
          Sessions expire automatically. Never share your credentials.
        </p>
      </div>
    </div>
  );
}
