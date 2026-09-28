import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { presetForSlug } from '../config/business';
import type { BusinessPreset } from '../config/business';
import type { AuthResponse, AvailableBusiness, MeResponse } from '../types';
import { api, clearTokens, setTokens, subscribeUnauthorized, ApiError } from './api';

/**
 * Session/auth state (React context + in-memory tokens).
 *
 * Flow: login -> tokens in memory -> /auth/me (user + business +
 * permissions) -> dashboard. Handles 401/403, refresh, logout,
 * revoked sessions, inactive user/membership via explicit status —
 * the UI never sits in a broken infinite loader.
 */

export type SessionStatus =
  | 'loading'
  | 'anonymous'
  | 'authenticated'
  | 'forbidden';

interface SessionValue {
  status: SessionStatus;
  me: MeResponse | null;
  businesses: AvailableBusiness[];
  preset: BusinessPreset;
  permissions: string[];
  role: string | null;
  businessId: string | null;
  login: (email: string, password: string, businessSlug?: string) => Promise<void>;
  logout: () => Promise<void>;
  switchBusiness: (businessIdOrSlug: string) => Promise<void>;
  refreshMe: () => Promise<void>;
  can: (permission: string) => boolean;
  authError: string | null;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }): JSX.Element {
  const [status, setStatus] = useState<SessionStatus>('loading');
  const [me, setMe] = useState<MeResponse | null>(null);
  const [businesses, setBusinesses] = useState<AvailableBusiness[]>([]);
  const [authError, setAuthError] = useState<string | null>(null);

  const loadMe = useCallback(async (): Promise<boolean> => {
    try {
      const data = await api.get<MeResponse>('/api/v1/auth/me');
      setMe(data);
      setStatus(data.business ? 'authenticated' : 'forbidden');
      return true;
    } catch {
      setMe(null);
      setStatus('anonymous');
      return false;
    }
  }, []);

  const loadBusinesses = useCallback(async (): Promise<void> => {
    try {
      const list = await api.get<AvailableBusiness[]>('/api/v1/auth/businesses');
      setBusinesses(list);
    } catch {
      setBusinesses([]);
    }
  }, []);

  useEffect(() => {
    subscribeUnauthorized(() => {
      clearTokens();
      setMe(null);
      setStatus('anonymous');
    });
    // Try a silent session restore on boot (cookie-based refresh).
    (async () => {
      try {
        const data = await api.authPost<AuthResponse>('/api/v1/auth/refresh', {
          refresh_token: null,
        });
        setTokens({ access: data.access_token, refresh: data.refresh_token });
        await loadMe();
        await loadBusinesses();
      } catch {
        setStatus('anonymous');
      }
    })();
  }, [loadBusinesses, loadMe]);

  const login = useCallback(
    async (email: string, password: string, businessSlug?: string) => {
      setAuthError(null);
      try {
        let data: AuthResponse;
        try {
          data = await api.authPost<AuthResponse>('/api/v1/auth/login', {
            email,
            password,
            business_slug: businessSlug || undefined,
          });
        } catch (err) {
          // The configured slug is only a hint: staff whose membership
          // lives in another business fall back to their default
          // membership (backend still verifies everything server-side).
          if (err instanceof ApiError && err.kind === 'forbidden' && businessSlug) {
            data = await api.authPost<AuthResponse>('/api/v1/auth/login', {
              email,
              password,
            });
          } else {
            throw err;
          }
        }
        setTokens({ access: data.access_token, refresh: data.refresh_token });
        await loadMe();
        await loadBusinesses();
      } catch (err) {
        clearTokens();
        setStatus('anonymous');
        setAuthError(err instanceof Error ? err.message : 'Sign in failed.');
        throw err;
      }
    },
    [loadBusinesses, loadMe],
  );

  const logout = useCallback(async () => {
    try {
      await api.post('/api/v1/auth/logout', { refresh_token: null });
    } catch {
      // Logout is best-effort client-side; the session row revocation
      // already happened server-side when reachable.
    }
    clearTokens();
    setMe(null);
    setBusinesses([]);
    setStatus('anonymous');
  }, []);

  const switchBusiness = useCallback(
    async (businessIdOrSlug: string) => {
      const data = await api.post<AuthResponse>('/api/v1/auth/switch-business', {
        business_id: businessIdOrSlug,
      });
      setTokens({ access: data.access_token, refresh: data.refresh_token });
      await loadMe();
    },
    [loadMe],
  );

  const refreshMe = useCallback(async () => {
    await loadMe();
    await loadBusinesses();
  }, [loadBusinesses, loadMe]);

  const value = useMemo<SessionValue>(() => {
    const permissions = me?.permissions ?? [];
    return {
      status,
      me,
      businesses,
      preset: presetForSlug(me?.business?.slug),
      permissions,
      role: me?.membership?.role ?? null,
      businessId: me?.business?.id ?? null,
      login,
      logout,
      switchBusiness,
      refreshMe,
      can: (permission: string) => permissions.includes(permission),
      authError,
    };
  }, [status, me, businesses, login, logout, switchBusiness, refreshMe, authError]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession must be used inside SessionProvider.');
  return ctx;
}
