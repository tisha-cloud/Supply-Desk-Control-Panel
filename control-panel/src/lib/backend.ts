/**
 * Client for the FastAPI backend that runs the extraction pipeline, the
 * workbook import and the deck generator.
 *
 * Calls go through Next.js route handlers under /api/backend/* rather than
 * straight to :8000, so the backend URL stays server-side and there is no CORS
 * negotiation in the browser.
 */
import type { AccessUser, Me, Permission, Role } from "./access";
import type {
  DeckFormat,
  DeckPreview,
  DemographyProfile,
  DuplicateGroup,
  IngestJob,
} from "./types";

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
  /** False until migration 0006 has been run: every route is open until then. */
  auth_ready?: boolean;
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

  // ------------------------------------------------------------ user access
  me: () => request<Me>("/api/me"),

  permissions: () => request<Permission[]>("/api/access/permissions"),

  roles: () => request<Role[]>("/api/access/roles"),

  createRole: (body: { name: string; permissions: string[]; description?: string }) =>
    request<Role>("/api/access/roles", { method: "POST", body: JSON.stringify(body) }),

  updateRole: (
    key: string,
    body: { name?: string; permissions?: string[]; description?: string },
  ) =>
    request<Role>(`/api/access/roles/${encodeURIComponent(key)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  deleteRole: (key: string) =>
    request<{ deleted: string }>(`/api/access/roles/${encodeURIComponent(key)}`, {
      method: "DELETE",
    }),

  users: () => request<AccessUser[]>("/api/access/users"),

  createUser: (body: {
    email: string;
    password: string;
    role_key: string;
    full_name?: string | null;
  }) => request<{ id: string }>("/api/access/users", { method: "POST", body: JSON.stringify(body) }),

  updateUser: (
    id: string,
    body: { role_key?: string; is_active?: boolean; full_name?: string },
  ) =>
    request<AccessUser>(`/api/access/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  setUserPassword: (id: string, password: string) =>
    request<{ updated: string }>(`/api/access/users/${id}/password`, {
      method: "POST",
      body: JSON.stringify({ password }),
    }),

  deleteUser: (id: string) =>
    request<{ deleted: string }>(`/api/access/users/${id}`, { method: "DELETE" }),

  profileDemography: (body: { text?: string; pincodes?: string[] }) =>
    request<DemographyProfile>("/api/demography/profile", {
      method: "POST",
      body: JSON.stringify(body),
    }),

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
