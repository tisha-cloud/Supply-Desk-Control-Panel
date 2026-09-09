"use client";

import { createBrowserClient } from "@supabase/ssr";

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

export function createClient() {
  if (!SUPABASE_URL || !SUPABASE_KEY) {
    throw new Error(
      "Supabase is not configured. Copy .env.local.example to .env.local and set " +
        "NEXT_PUBLIC_SUPABASE_URL plus NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY " +
        "(or NEXT_PUBLIC_SUPABASE_ANON_KEY on a legacy project).",
    );
  }
  return createBrowserClient(SUPABASE_URL, SUPABASE_KEY);
}

export function isSupabaseConfigured(): boolean {
  return Boolean(SUPABASE_URL && SUPABASE_KEY);
}

/** Public URL for an object in the building-images bucket. */
export function imageUrl(storagePath: string): string {
  if (!SUPABASE_URL || !storagePath) return "";
  return `${SUPABASE_URL}/storage/v1/object/public/building-images/${storagePath}`;
}
