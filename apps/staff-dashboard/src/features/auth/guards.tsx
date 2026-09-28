import { Navigate, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useSession } from '../../lib/auth';
import { CardsSkeleton } from '../../components/ui/states';

/** Redirect anonymous users to /login (remembers the target). */
export function RequireAuth({ children }: { children: ReactNode }): JSX.Element {
  const { status } = useSession();
  const location = useLocation();

  if (status === 'loading') {
    return (
      <div className="mx-auto max-w-6xl px-4 pt-10">
        <CardsSkeleton />
      </div>
    );
  }
  if (status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (status === 'forbidden') {
    return (
      <div className="mx-auto max-w-lg px-4 pt-20 text-center">
        <h1 className="text-xl font-bold text-slate-900">No active business</h1>
        <p className="mt-2 text-sm text-slate-500">
          Your account is not a member of an active business. Ask an administrator to invite you.
        </p>
      </div>
    );
  }
  return <>{children}</>;
}

/** Hide content the role may not use (backend still enforces). */
export function RequirePermission({
  permission,
  fallback,
  children,
}: {
  permission: string;
  fallback?: ReactNode;
  children: ReactNode;
}): JSX.Element {
  const { can } = useSession();
  if (!can(permission)) return <>{fallback ?? null}</>;
  return <>{children}</>;
}
