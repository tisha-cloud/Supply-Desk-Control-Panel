"use client";

import useSWR from "swr";
import { backend } from "@/lib/backend";
import { relativeTime } from "@/lib/format";
import { Callout, ProgressBar, StatusChip } from "./ui";
import type { IngestJob } from "@/lib/types";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

/**
 * Follows one ingest job. Polls only while the job is live, then stops - these
 * runs take minutes and a finished job never changes again.
 */
export function JobMonitor({ jobId, onDone }: { jobId: string; onDone?: (job: IngestJob) => void }) {
  const { data: job } = useSWR<IngestJob>(
    jobId ? ["job", jobId] : null,
    () => backend.job(jobId),
    {
      refreshInterval: (latest) => (latest && TERMINAL.has(latest.status) ? 0 : 1500),
      onSuccess: (latest) => {
        if (latest && TERMINAL.has(latest.status)) onDone?.(latest);
      },
    },
  );

  if (!job) return null;

  const stats = (job.stats ?? {}) as Record<string, unknown>;
  const numericStats = Object.entries(stats).filter(
    ([, value]) => typeof value === "number" && value > 0,
  ) as [string, number][];

  return (
    <div className="card animate-in overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-surface-2 px-5 py-3">
        <div className="flex items-center gap-2.5">
          <StatusChip status={job.status} />
          <span className="text-sm font-medium">{job.label || job.kind}</span>
        </div>
        <span className="text-xs text-ink-3">
          started {relativeTime(job.started_at ?? job.created_at)}
        </span>
      </div>

      <div className="p-5">
        {job.total_files > 0 ? (
          <>
            <div className="mb-2 flex items-baseline justify-between text-sm">
              <span className="font-medium tabular-nums">
                {job.done_files}
                <span className="text-ink-3"> / {job.total_files}</span>
              </span>
              <span className="text-xs text-ink-3 tabular-nums">
                {job.buildings_upserted} buildings · {job.spaces_upserted} spaces
                {job.images_uploaded ? ` · ${job.images_uploaded} images` : ""}
              </span>
            </div>
            <ProgressBar value={job.done_files} max={job.total_files} />
          </>
        ) : null}

        {job.error ? (
          <div className="mt-4">
            <Callout tone="danger" title="Run failed">
              <pre className="max-h-40 overflow-auto text-xs whitespace-pre-wrap">{job.error}</pre>
            </Callout>
          </div>
        ) : null}

        {job.status === "succeeded" && numericStats.length > 0 ? (
          <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {numericStats.map(([key, value]) => (
              <div key={key} className="rounded-lg bg-surface-2 px-3 py-2">
                <dt className="text-xs text-ink-3 capitalize">{key.replace(/_/g, " ")}</dt>
                <dd className="mt-0.5 font-semibold tabular-nums">{value.toLocaleString()}</dd>
              </div>
            ))}
          </dl>
        ) : null}

        {job.log ? (
          <details className="mt-4">
            <summary className="cursor-pointer text-xs text-ink-3 select-none hover:text-ink-2">
              Run log
            </summary>
            <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-surface-2 p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
              {job.log}
            </pre>
          </details>
        ) : null}
      </div>
    </div>
  );
}
