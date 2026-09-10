"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import {
  FileStack,
  FileText,
  Keyboard,
  Play,
  Settings2,
  Upload,
} from "lucide-react";
import { backend, BackendError } from "@/lib/backend";
import { relativeTime } from "@/lib/format";
import { JobMonitor } from "@/components/JobMonitor";
import {
  Callout,
  EmptyState,
  PageHeader,
  Section,
  StatusChip,
  TableSkeleton,
  useToast,
} from "@/components/ui";
import type { IngestJob } from "@/lib/types";

export default function ExtractionPage() {
  const toast = useToast();

  const [files, setFiles] = useState<FileList | null>(null);
  const [landlord, setLandlord] = useState("");
  const [staged, setStaged] = useState<string | null>(null);

  const [advanced, setAdvanced] = useState(false);
  const [developer, setDeveloper] = useState("");
  const [limit, setLimit] = useState(0);
  const [cacheOnly, setCacheOnly] = useState(false);
  const [gapfill, setGapfill] = useState(false);

  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState<"upload" | "run" | null>(null);

  const { data: health } = useSWR("backend-health", () => backend.health(), {
    shouldRetryOnError: false,
  });
  const { data: jobs, isLoading, mutate: refreshJobs } = useSWR<IngestJob[]>(
    "jobs-extraction",
    () => backend.jobs("extraction"),
    { shouldRetryOnError: false },
  );

  const ready = Boolean(health?.supabase_configured);

  async function startRun(scope: string | null) {
    setBusy("run");
    try {
      const result = await backend.runExtraction({
        developer: scope,
        limit: Number(limit) || 0,
        cache_only: cacheOnly,
        gapfill,
      });
      setJobId(result.job_id);
      toast({
        tone: "info",
        message: scope ? `Reading documents for “${scope}”.` : "Reading every document in the supply folder.",
      });
    } catch (err) {
      toast({
        tone: "danger",
        title: "Could not start",
        message: err instanceof BackendError ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }

  async function uploadFiles(runAfter: boolean) {
    if (!files?.length || !landlord.trim()) return;
    setBusy("upload");
    try {
      const form = new FormData();
      form.append("developer", landlord.trim());
      Array.from(files).forEach((file) => form.append("files", file));

      const response = await fetch("/api/backend/api/extraction/upload", {
        method: "POST",
        body: form,
      });
      if (!response.ok) throw new Error((await response.json()).detail ?? "Upload failed");
      const result = await response.json();
      setStaged(`${result.staged} file(s) filed under “${result.developer}”.`);
      setFiles(null);
      toast({ tone: "success", title: "Files added", message: result.developer });
      if (runAfter) await startRun(landlord.trim());
    } catch (err) {
      toast({
        tone: "danger",
        title: "Upload failed",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Supply intake"
        title="Document Intake"
        description="Turn landlord documents into database records. Availability reports, pitch decks, rent cards, spreadsheets and WhatsApp screenshots all work; occupied space is derived from what each document leaves out."
      />

      {health && !ready ? (
        <div className="mb-6">
          <Callout tone="warning" title="Supabase is not configured on the backend">
            Extraction publishes straight to the database, so it will refuse to start until{" "}
            <code>control-panel/backend/.env</code> has your secret key.
          </Callout>
        </div>
      ) : null}

      {/* --------------------------------------------------- primary: upload */}
      <Section
        title="Add documents"
        description="One file or a whole folder's worth. Files are filed under the landlord you name, because the pipeline takes the landlord from the folder."
        className="mb-5"
      >
        <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
          <div>
            <label className="label" htmlFor="landlord">
              Landlord or operator
            </label>
            <input
              id="landlord"
              className="field"
              placeholder="e.g. Bagmane"
              value={landlord}
              onChange={(e) => setLandlord(e.target.value)}
            />
            <p className="mt-2 text-xs text-ink-3">
              Use the name as you want it stored. Existing landlords are matched automatically.
            </p>
          </div>

          <div>
            <label className="label" htmlFor="upload-files">
              Documents
            </label>
            <label
              htmlFor="upload-files"
              className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed border-border-strong px-4 py-9 text-center transition-colors hover:border-accent hover:bg-accent-soft/40"
            >
              <FileStack className="h-6 w-6 text-ink-3" aria-hidden />
              <span className="text-sm font-medium">
                {files?.length ? `${files.length} file(s) selected` : "Choose files"}
              </span>
              <span className="text-xs text-ink-3">PDF · PPTX · XLSX · JPG · PNG</span>
              <input
                id="upload-files"
                type="file"
                multiple
                accept=".pdf,.pptx,.xlsx,.xls,.jpg,.jpeg,.png,.webp"
                className="sr-only"
                onChange={(e) => setFiles(e.target.files)}
              />
            </label>
          </div>
        </div>

        {staged ? (
          <div className="mt-4">
            <Callout tone="success" onDismiss={() => setStaged(null)}>
              {staged}
            </Callout>
          </div>
        ) : null}

        <div className="mt-5 flex flex-wrap gap-2">
          <button
            className="btn-primary"
            onClick={() => uploadFiles(true)}
            disabled={busy !== null || !files?.length || !landlord.trim() || !ready}
          >
            <Play className="h-4 w-4" aria-hidden />
            {busy === "upload" ? "Uploading…" : "Upload and extract"}
          </button>
          <button
            className="btn-secondary"
            onClick={() => uploadFiles(false)}
            disabled={busy !== null || !files?.length || !landlord.trim()}
          >
            <Upload className="h-4 w-4" aria-hidden />
            Upload only
          </button>
        </div>
      </Section>

      {/* ------------------------------------------------ secondary entries */}
      <div className="mb-5 grid gap-4 md:grid-cols-2">
        <Section title="Re-read everything">
          <p className="text-sm text-ink-2">
            Runs the pipeline over every document already in the supply folder. Byte-identical
            copies and older monthly editions are skipped automatically.
          </p>
          {health?.supply_dir ? (
            <p
              className="mt-3 truncate rounded-lg bg-surface-2 px-3 py-2 font-mono text-xs text-ink-2"
              title={health.supply_dir}
            >
              {health.supply_dir}
            </p>
          ) : null}
          <button
            className="btn-secondary mt-4 w-full"
            onClick={() => startRun(null)}
            disabled={busy !== null || !ready}
          >
            <FileText className="h-4 w-4" aria-hidden />
            Read all documents
          </button>
        </Section>

        <Section title="Enter one by hand">
          <p className="text-sm text-ink-2">
            No document to work from? Create the building directly and fill in its floors,
            contacts and photographs yourself. It lands in the same database.
          </p>
          <Link href="/data/new" className="btn-secondary mt-4 w-full">
            <Keyboard className="h-4 w-4" aria-hidden />
            Add a building manually
          </Link>
        </Section>
      </div>

      {/* ---------------------------------------------------------- advanced */}
      <div className="mb-6">
        <button
          className="btn-ghost -ml-2"
          onClick={() => setAdvanced((v) => !v)}
          aria-expanded={advanced}
        >
          <Settings2 className="h-4 w-4" aria-hidden />
          {advanced ? "Hide run options" : "Run options"}
        </button>

        {advanced ? (
          <div className="animate-in mt-3">
            <Section>
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="label" htmlFor="developer">
                    Landlord filter
                  </label>
                  <input
                    id="developer"
                    className="field"
                    placeholder="All landlords"
                    value={developer}
                    onChange={(e) => setDeveloper(e.target.value)}
                  />
                </div>
                <div>
                  <label className="label" htmlFor="limit">
                    File limit
                  </label>
                  <input
                    id="limit"
                    type="number"
                    min={0}
                    className="field"
                    placeholder="0 = no limit"
                    value={limit || ""}
                    onChange={(e) => setLimit(Number(e.target.value))}
                  />
                </div>
              </div>

              <div className="mt-4 space-y-3">
                <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-border p-3 text-sm transition-colors hover:bg-surface-2">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={cacheOnly}
                    onChange={(e) => setCacheOnly(e.target.checked)}
                  />
                  <span>
                    <span className="font-medium">Replay cached results only</span>
                    <span className="mt-0.5 block text-xs text-ink-3">
                      Rebuilds from stored model responses without spending any LLM quota.
                    </span>
                  </span>
                </label>
                <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-border p-3 text-sm transition-colors hover:bg-surface-2">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={gapfill}
                    onChange={(e) => setGapfill(e.target.checked)}
                  />
                  <span>
                    <span className="font-medium">Second pass for missing building sizes</span>
                    <span className="mt-0.5 block text-xs text-ink-3">
                      Roughly doubles LLM calls. Worth it only when totals come back empty.
                    </span>
                  </span>
                </label>
              </div>

              <button
                className="btn-primary mt-5"
                onClick={() => startRun(developer.trim() || null)}
                disabled={busy !== null || !ready}
              >
                <Play className="h-4 w-4" aria-hidden />
                Run with these options
              </button>
            </Section>
          </div>
        ) : null}
      </div>

      {jobId ? (
        <div className="mb-8">
          <h2 className="mb-3 font-semibold tracking-tight">Current run</h2>
          <JobMonitor jobId={jobId} onDone={() => refreshJobs()} />
        </div>
      ) : null}

      <div>
        <h2 className="mb-3 font-semibold tracking-tight">Recent runs</h2>
        {isLoading ? (
          <TableSkeleton rows={3} />
        ) : !jobs || jobs.length === 0 ? (
          <EmptyState icon={Play} title="No extraction runs yet">
            Upload a document above, or read everything already in the supply folder.
          </EmptyState>
        ) : (
          <div className="card table-scroll overflow-hidden">
            <table className="w-full min-w-[680px]">
              <thead className="bg-surface-2">
                <tr>
                  <th className="th">Status</th>
                  <th className="th">Scope</th>
                  <th className="th text-right">Files</th>
                  <th className="th text-right">Buildings</th>
                  <th className="th text-right">Spaces</th>
                  <th className="th text-right">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {jobs.map((job) => (
                  <tr
                    key={job.id}
                    className="row-hover cursor-pointer"
                    onClick={() => setJobId(job.id)}
                  >
                    <td className="td">
                      <StatusChip status={job.status} />
                    </td>
                    <td className="td">{job.label || "All landlords"}</td>
                    <td className="td text-right tabular-nums">
                      {job.done_files}/{job.total_files}
                    </td>
                    <td className="td text-right tabular-nums">{job.buildings_upserted}</td>
                    <td className="td text-right tabular-nums">{job.spaces_upserted}</td>
                    <td className="td text-right text-ink-3">{relativeTime(job.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
