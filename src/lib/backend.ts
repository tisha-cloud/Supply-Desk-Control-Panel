/**
 * Client for the FastAPI backend that runs the extraction pipeline, the
 * workbook import and the deck generator.
 *
 * Calls go through Next.js route handlers under /api/backend/* rather than
 * straight to :8000, so the backend URL stays server-side and there is no CORS
 * negotiation in the browser.
 */
import type { DeckFormat, DeckPreview, DuplicateGroup, IngestJob } from "./types";

export const BACKEND_URL =
  process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

export class BackendError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/backend${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      detail = body.detail ?? body.error ?? detail;
    } catch {
      /* keep the generic message */
    }
    throw new BackendError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export interface HealthResponse {
  status: string;
  row_counts?: Record<string, number>;
  supabase_configured: boolean;
  llm_provider: string;
  supply_dir: string;
  supply_dir_exists: boolean;
  templates: string[];
}

export const backend = {
  health: () => request<HealthResponse>("/api/health"),

  runExtraction: (body: {
    developer?: string | null;
    limit?: number;
    cache_only?: boolean;
    gapfill?: boolean;
  }) =>
    request<{ job_id: string; status: string }>("/api/extraction/run", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  importManagedWorkbook: (body: {
    server_path?: string;
    upload_images?: boolean;
    supply_type?: string;
    dry_run?: boolean;
  }) =>
    request<{
      job_id?: string;
      status: string;
      source: string;
      dry_run?: boolean;
      stats?: Record<string, number | string | boolean | unknown[]>;
    }>("/api/import/managed-xlsx", { method: "POST", body: JSON.stringify(body) }),

  job: (id: string) => request<IngestJob>(`/api/jobs/${id}`),

  jobs: (kind?: string) =>
    request<IngestJob[]>(`/api/jobs${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`),

  templates: () => request<string[]>("/api/templates"),

  duplicateOrganisations: () =>
    request<DuplicateGroup[]>("/api/dedup/organisations"),

  mergeOrganisations: (body: { keep_id: string; merge_ids: string[] }) =>
    request<{ buildings: number; spaces: number; contacts: number; removed: number }>(
      "/api/dedup/organisations/merge",
      { method: "POST", body: JSON.stringify(body) },
    ),

  previewDeck: (body: { query: string }) =>
    request<DeckPreview>("/api/decks/preview", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  generateDeck: (body: {
    query: string;
    client_name?: string;
    template_name?: string | null;
    building_ids?: string[];
    output_format?: DeckFormat;
  }) =>
    request<{
      deck_id: string | null;
      filename: string;
      format: DeckFormat;
      options: number;
      criteria: Record<string, unknown>;
      building_ids: string[];
      download_url: string;
    }>("/api/decks/generate", { method: "POST", body: JSON.stringify(body) }),
};
