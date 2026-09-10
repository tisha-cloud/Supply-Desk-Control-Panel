import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";

/**
 * Server-side Supabase client backed by the request cookies.
 *
 * The browser client keeps the session in cookies rather than localStorage, so
 * middleware, route handlers and server components can all read who is signed
 * in. This is also how the backend proxy gets an access token to forward: a
 * plain download link carries cookies but no Authorization header.
 */
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_KEY =
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export function isConfigured(): boolean {
  return Boolean(SUPABASE_URL && SUPABASE_KEY);
}

export async function createServerSupabase() {
  const store = await cookies();
  return createServerClient(SUPABASE_URL!, SUPABASE_KEY!, {
    cookies: {
      getAll: () => store.getAll(),
      setAll: (list) => {
        try {
          list.forEach(({ name, value, options }) => store.set(name, value, options));
        } catch {
          // Called from a server component, where cookies are read-only. The
          // middleware refreshes the session, so nothing is lost here.
        }
      },
    },
  });
}

/** The current access token, or null when nobody is signed in. */
export async function accessToken(): Promise<string | null> {
  if (!isConfigured()) return null;
  try {
    const supabase = await createServerSupabase();
    const { data } = await supabase.auth.getSession();
    return data.session?.access_token ?? null;
  } catch {
    return null;
  }
}
