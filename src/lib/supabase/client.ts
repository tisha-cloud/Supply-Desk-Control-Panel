"use client";

import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

/**
 * Browser Supabase client.
 *
 * Supabase is migrating its key names: legacy projects issue an `anon` key,
 * newer ones a `sb_publishable_...` key. Both do the same job here - they are
 * safe in the browser and governed by RLS - so either env var is accepted.
 * Bulk ingest never runs on the client; that is the FastAPI backend's job.
 */
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_KEY =
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

// One client per tab. Auth state changes are broadcast to subscribers of a
// single instance, so creating a fresh client per call would leave components
// listening to a client that nothing signs in or out.
let browserClient: SupabaseClient | null = null;

export function createClient() {
  if (!SUPABASE_URL || !SUPABASE_KEY) {
    throw new Error(
      "Supabase is not configured. Copy .env.local.example to .env.local and set " +
        "NEXT_PUBLIC_SUPABASE_URL plus NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY " +
        "(or NEXT_PUBLIC_SUPABASE_ANON_KEY on a legacy project).",
    );
  }
  if (!browserClient) {
    browserClient = createBrowserClient(SUPABASE_URL, SUPABASE_KEY);
  }
  return browserClient;
}

export function isSupabaseConfigured(): boolean {
  return Boolean(SUPABASE_URL && SUPABASE_KEY);
}

/** Public URL for an object in the building-images bucket. */
export function imageUrl(storagePath: string): string {
  if (!SUPABASE_URL || !storagePath) return "";
  return `${SUPABASE_URL}/storage/v1/object/public/building-images/${storagePath}`;
}
