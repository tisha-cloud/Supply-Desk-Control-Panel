import { NextResponse, type NextRequest } from "next/server";
import { createServerClient } from "@supabase/ssr";

/**
 * Session refresh and the sign-in gate.
 *
 * Two jobs, both of which have to happen before a page renders:
 *
 *   1. Refresh the Supabase session. Access tokens are short-lived; without a
 *      refresh on every request the app signs itself out mid-session.
 *   2. Send anyone without a session to /login, remembering where they were
 *      going so they land there afterwards.
 *
 * This is a redirect, not a security boundary. What actually stops a signed-out
 * caller reading data is row-level security in Postgres and the permission
 * guards on the FastAPI routes.
 */
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_KEY =
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

/** Reachable without a session. */
const PUBLIC_PATHS = ["/login", "/auth/callback"];

/**
 * The one-time escape hatch for a database that has no accounts yet.
 *
 * Before migration 0006 there are no users, so the gate below would strand the
 * operator at a form nobody can satisfy. Setting AUTH_SETUP_MODE=1 opens the
 * app until the migration has been run, and it must then be removed.
 *
 * This used to be decided by asking the backend on each cold start. That was
 * wrong in a way that only showed up once deployed: the probe treated an
 * unreachable backend as "authentication is not set up", so a serverless
 * instance that could not reach a sleeping backend within its timeout let
 * everyone through. The default is now to enforce, and only an explicit,
 * deliberate environment variable relaxes it.
 */
const SETUP_MODE = process.env.AUTH_SETUP_MODE === "1";

export async function middleware(request: NextRequest) {
  // Without credentials there is nothing to sign in to; let the setup notice
  // on the page explain that rather than redirecting into a login that cannot
  // work either.
  if (!SUPABASE_URL || !SUPABASE_KEY) return NextResponse.next();
  if (SETUP_MODE) return NextResponse.next();

  let response = NextResponse.next({ request });

  const supabase = createServerClient(SUPABASE_URL, SUPABASE_KEY, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (list) => {
        list.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        list.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      },
    },
  });

  // getUser, not getSession: it revalidates the token with the Auth server, so
  // a deleted or deactivated account stops working immediately.
  const { data } = await supabase.auth.getUser();
  const { pathname } = request.nextUrl;
  const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p));

  if (!data.user && !isPublic) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname + request.nextUrl.search);
    return NextResponse.redirect(url);
  }

  if (data.user && pathname === "/login") {
    const url = request.nextUrl.clone();
    url.pathname = request.nextUrl.searchParams.get("next") || "/";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return response;
}

export const config = {
  matcher: [
    /*
     * Everything except Next internals and static assets. /api/backend is
     * included on purpose: the proxy needs the refreshed session to forward a
     * valid token to FastAPI.
     */
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
