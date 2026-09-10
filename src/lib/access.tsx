"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { createClient, isSupabaseConfigured } from "@/lib/supabase/client";

/**
 * Who is signed in, and what they are allowed to do.
 *
 * The permission list comes from the backend rather than being inferred in the
 * browser, so there is one definition of a role. It decides what to *render*;
 * it is never what stops an action. A viewer who calls the API directly is
 * refused by the FastAPI guard, and one who talks to Supabase directly is
 * refused by row-level security.
 */

export interface Me {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  permissions: string[];
  is_active: boolean;
}

interface AccessState {
  me: Me | null;
  loading: boolean;
  /** False until migration 0006 has been run; everything is open until then. */
  authReady: boolean;
  can: (permission: string) => boolean;
  signOut: () => Promise<void>;
  refresh: () => void;
}

const AccessContext = createContext<AccessState>({
  me: null,
  loading: true,
  authReady: false,
  can: () => false,
  signOut: async () => {},
  refresh: () => {},
});

export function AccessProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const status = await fetch("/api/backend/api/access/status").then((r) => r.json());
        if (cancelled) return;
        setAuthReady(Boolean(status.auth_ready));

        const response = await fetch("/api/backend/api/me");
        if (cancelled) return;
        setMe(response.ok ? await response.json() : null);
      } catch {
        if (!cancelled) setMe(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  const can = useCallback(
    (permission: string) => {
      // Before migration 0006 there are no roles to check against, and the
      // backend leaves its routes open to match. Hiding the UI here would make
      // the tool look broken during setup.
      if (!authReady) return true;
      if (!me) return false;
      return me.permissions.includes("*") || me.permissions.includes(permission);
    },
    [me, authReady],
  );

  const signOut = useCallback(async () => {
    if (isSupabaseConfigured()) {
      try {
        await createClient().auth.signOut();
      } catch {
        /* signing out locally is enough to lose the session */
      }
    }
    // A full page load, not router.push: the middleware has to re-read the
    // cleared cookie, and every cached page of the old session must be dropped.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = "/login";
  }, []);

  const value = useMemo<AccessState>(
    () => ({ me, loading, authReady, can, signOut, refresh: () => setNonce((n) => n + 1) }),
    [me, loading, authReady, can, signOut],
  );

  return <AccessContext.Provider value={value}>{children}</AccessContext.Provider>;
}

export function useAccess(): AccessState {
  return useContext(AccessContext);
}

/** Render children only when the signed-in user holds this permission. */
export function Can({
  permission,
  children,
  fallback = null,
}: {
  permission: string;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  const { can } = useAccess();
  return <>{can(permission) ? children : fallback}</>;
}

/** The permission catalogue, grouped for the role editor. */
export interface Permission {
  key: string;
  label: string;
  description: string;
  category: string;
  sort_order: number;
}

export interface Role {
  key: string;
  name: string;
  description: string | null;
  permissions: string[];
  is_system: boolean;
  user_count: number;
}

export interface AccessUser {
  id: string;
  email: string;
  full_name: string | null;
  role_key: string;
  role_name: string;
  permissions: string[];
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
  last_sign_in_at: string | null;
}

/** A role holding the wildcard can do everything, including future features. */
export function roleGrants(role: Role, permission: string): boolean {
  return role.permissions.includes("*") || role.permissions.includes(permission);
}
