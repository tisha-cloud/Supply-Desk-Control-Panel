"use client";

import { Callout } from "./ui";

/**
 * Shown wherever the app needs Supabase but has no credentials yet. Every
 * feature depends on the database, so failing with instructions beats failing
 * with a stack trace.
 */
export function SetupNotice() {
  return (
    <Callout tone="warning" title="Supabase is not connected yet">
      <p>Credentials go in two places, because the browser and the backend use different keys.</p>
      <ol className="mt-2.5 ml-4 list-decimal space-y-1.5">
        <li>
          <code>control-panel/.env.local</code> — <code>NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
          <code>NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY</code> (the publishable key is safe in
          the browser and governed by row-level security).
        </li>
        <li>
          <code>backend/.env</code> — <code>SUPABASE_URL</code> and{" "}
          <code>SUPABASE_SECRET_KEY</code>. The secret key bypasses RLS, so it stays
          server-side only.
        </li>
      </ol>
      <p className="mt-2.5">
        Then run both migrations in <code>control-panel/supabase/migrations/</code> from the
        Supabase SQL editor, oldest first.
      </p>
    </Callout>
  );
}

/** True when Supabase answered but the schema has not been created yet. */
export function isMissingSchema(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return /PGRST205|Could not find the table|schema cache/i.test(message);
}

/**
 * The credentials are good but the migrations have not been run. This is the
 * expected state immediately after connecting a fresh project, so it gets its
 * own instructions rather than a raw PostgREST error.
 */
export function MigrationNotice() {
  return (
    <Callout tone="warning" title="Connected to Supabase, but the tables do not exist yet">
      <p>Run the two migrations from the Supabase SQL editor, oldest first:</p>
      <ol className="mt-2.5 ml-4 list-decimal space-y-1">
        <li>
          <code>supabase/migrations/0001_init.sql</code> — tables, views and triggers
        </li>
        <li>
          <code>supabase/migrations/0002_rls_and_storage.sql</code> — storage buckets and
          row-level security
        </li>
      </ol>
      <p className="mt-2.5">
        Paste each file's contents into a new query and run it. Reload this page afterwards.
      </p>
    </Callout>
  );
}

/**
 * The backend can see rows that the browser cannot.
 *
 * The browser reads with the publishable key as the `anon` role; the backend
 * reads with the secret key and bypasses RLS. When one sees data and the other
 * does not, the cause is always a missing `anon` policy - never an empty table.
 */
export function RlsNotice({ backendRows }: { backendRows: number }) {
  return (
    <Callout tone="danger" title="Row-level security is hiding the data from your browser">
      <p>
        The database holds <strong>{backendRows.toLocaleString()} buildings</strong>, but this page
        reads with the publishable key as the <code>anon</code> role, and no policy grants it
        access — so Supabase returns an empty list rather than an error.
      </p>
      <p className="mt-2">
        Run <code>supabase/migrations/0004_anon_access.sql</code> in the Supabase SQL editor, then
        reload. Read the comment at the top of that file first: it grants anyone holding the
        publishable key full access, which suits an internal tool but not a public one.
      </p>
    </Callout>
  );
}
