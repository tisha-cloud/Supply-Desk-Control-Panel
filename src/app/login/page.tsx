"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AlertCircle, LogIn } from "lucide-react";
import { createClient, isSupabaseConfigured } from "@/lib/supabase/client";

function LoginForm() {
  const params = useSearchParams();
  const next = params.get("next") || "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const configured = isSupabaseConfigured();

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!configured) return;
    setBusy(true);
    setError(null);
    try {
      const { error: signInError } = await createClient().auth.signInWithPassword({
        email: email.trim(),
        password,
      });
      if (signInError) {
        // Supabase says "Invalid login credentials" for a wrong password and
        // for an address that has no account. Do not guess which; saying
        // "no such user" would confirm which addresses exist.
        setError(
          signInError.message === "Invalid login credentials"
            ? "That email and password do not match an account."
            : signInError.message,
        );
        return;
      }
      // A full navigation, not router.push: the middleware has to see the new
      // session cookie before the destination renders.
      window.location.href = next;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-dvh place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-7 flex flex-col items-center text-center">
          <span
            className="mb-3 grid h-11 w-11 place-items-center rounded-xl text-xs font-bold tracking-tight text-white"
            style={{ background: "var(--accent)" }}
          >
            BLR
          </span>
          <h1 className="text-xl font-semibold tracking-tight">Bangalore Supply Desk</h1>
          <p className="mt-1 text-sm text-ink-2">Sign in to continue</p>
        </div>

        {!configured ? (
          <div className="card p-4 text-sm">
            <p className="flex items-start gap-2 font-medium text-warning">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              Supabase is not configured
            </p>
            <p className="mt-2 text-ink-2">
              Copy <code>.env.local.example</code> to <code>.env.local</code> and set{" "}
              <code>NEXT_PUBLIC_SUPABASE_URL</code> and the publishable key, then restart the
              server.
            </p>
          </div>
        ) : (
          <form onSubmit={submit} className="card space-y-4 p-5">
            <div>
              <label className="label" htmlFor="email">
                Email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="username"
                required
                autoFocus
                className="field"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>

            <div>
              <label className="label" htmlFor="password">
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                className="field"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            {error ? (
              <p
                role="alert"
                className="flex items-start gap-2 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger"
              >
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                {error}
              </p>
            ) : null}

            <button className="btn-primary w-full justify-center" disabled={busy}>
              <LogIn className="h-4 w-4" aria-hidden />
              {busy ? "Signing in…" : "Sign in"}
            </button>

            <p className="text-center text-xs text-ink-3">
              Accounts are created by an administrator from the User Access screen.
            </p>
          </form>
        )}
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
