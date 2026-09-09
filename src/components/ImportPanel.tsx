"use client";

import { useState } from "react";
import { FlaskConical, Play, X } from "lucide-react";
import { backend, BackendError } from "@/lib/backend";
import { JobMonitor } from "./JobMonitor";
import { Callout, Section, useToast } from "./ui";
import { SUPPLY_TYPES, type SupplyTypeValue } from "@/lib/supply";

const DEFAULT_WORKBOOK =
  "C:\\Users\\devil\\Desktop\\full automation\\BLR - Managed Office Space Supply 2026.xlsx";

interface DryRunStats {
  sheets?: number;
  buildings?: number;
  spaces?: number;
  images?: number;
  operators?: number;
  contacts?: number;
  errors?: unknown[];
}

export function ImportPanel({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [path, setPath] = useState(DEFAULT_WORKBOOK);
  const [supplyType, setSupplyType] = useState<SupplyTypeValue>("managed");
  const [withImages, setWithImages] = useState(true);
  const [jobId, setJobId] = useState<string | null>(null);
  const [dryRun, setDryRun] = useState<DryRunStats | null>(null);
  const [busy, setBusy] = useState<"check" | "import" | null>(null);

  async function run(isDryRun: boolean) {
    setBusy(isDryRun ? "check" : "import");
    if (isDryRun) setDryRun(null);
    try {
      const result = await backend.importManagedWorkbook({
        server_path: path,
        upload_images: withImages,
        supply_type: supplyType,
        dry_run: isDryRun,
      });
      if (isDryRun) {
        setDryRun((result.stats ?? {}) as DryRunStats);
      } else if (result.job_id) {
        setJobId(result.job_id);
        toast({ tone: "info", message: "Import started. Progress appears below." });
      }
    } catch (err) {
      toast({
        tone: "danger",
        title: isDryRun ? "Could not read the workbook" : "Import could not start",
        message: err instanceof BackendError ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Section
      title="Import a supply workbook"
      description="Reads every micro-market sheet and lifts the embedded photographs into storage. Large files are read from disk rather than uploaded through the browser."
      actions={
        <button className="btn-ghost px-2" aria-label="Close" onClick={onClose}>
          <X className="h-4 w-4" aria-hidden />
        </button>
      }
    >
      <div>
        <label className="label" htmlFor="workbook">
          Workbook path on the machine running the backend
        </label>
        <input
          id="workbook"
          className="field font-mono text-xs"
          value={path}
          onChange={(e) => setPath(e.target.value)}
        />
      </div>

      <fieldset className="mt-5">
        <legend className="label">Import everything in this file as</legend>
        <div className="grid gap-2 sm:grid-cols-3">
          {SUPPLY_TYPES.filter((t) => t.importable).map((type) => {
            const active = supplyType === type.value;
            return (
              <button
                key={type.value}
                type="button"
                onClick={() => setSupplyType(type.value)}
                aria-pressed={active}
                className={`rounded-lg border p-3 text-left transition-colors ${
                  active
                    ? "border-accent bg-accent-soft"
                    : "border-border hover:border-border-strong hover:bg-surface-2"
                }`}
              >
                <span className={`block text-sm font-medium ${active ? "text-accent" : ""}`}>
                  {type.label}
                </span>
                <span className="mt-0.5 block text-xs text-ink-3">{type.hint}</span>
              </button>
            );
          })}
        </div>
      </fieldset>

      <label className="mt-4 flex cursor-pointer items-start gap-2.5 rounded-lg border border-border p-3 text-sm transition-colors hover:bg-surface-2">
        <input
          type="checkbox"
          className="mt-0.5"
          checked={withImages}
          onChange={(e) => setWithImages(e.target.checked)}
        />
        <span>
          <span className="font-medium">Upload embedded photographs</span>
          <span className="mt-0.5 block text-xs text-ink-3">
            Roughly 435 images and ~318 MB of Supabase storage for the Managed Office file —
            about a third of the free tier. Untick for a fast, data-only import.
          </span>
        </span>
      </label>

      <div className="mt-5 flex flex-wrap gap-2">
        <button className="btn-secondary" onClick={() => run(true)} disabled={busy !== null || !path.trim()}>
          <FlaskConical className="h-4 w-4" aria-hidden />
          {busy === "check" ? "Reading…" : "Check without importing"}
        </button>
        <button className="btn-primary" onClick={() => run(false)} disabled={busy !== null || !path.trim()}>
          <Play className="h-4 w-4" aria-hidden />
          {busy === "import" ? "Starting…" : "Import to database"}
        </button>
      </div>

      {dryRun ? (
        <div className="mt-5">
          <Callout
            tone={(dryRun.errors?.length ?? 0) > 0 ? "warning" : "success"}
            title="Workbook read successfully — nothing written yet"
          >
            <p className="mb-2">
              This is what the import would create, tagged as{" "}
              <strong>{SUPPLY_TYPES.find((t) => t.value === supplyType)?.label}</strong>.
            </p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
              {(
                [
                  ["Sheets", dryRun.sheets],
                  ["Buildings", dryRun.buildings],
                  ["Spaces", dryRun.spaces],
                  ["Photographs", dryRun.images],
                  ["Operators", dryRun.operators],
                  ["Contacts", dryRun.contacts],
                ] as [string, number | undefined][]
              ).map(([label, count]) => (
                <div key={label} className="flex justify-between gap-2">
                  <dt>{label}</dt>
                  <dd className="font-semibold tabular-nums">{count ?? 0}</dd>
                </div>
              ))}
            </dl>
            {(dryRun.errors?.length ?? 0) > 0 ? (
              <p className="mt-2 text-xs">{String(dryRun.errors?.[0])}</p>
            ) : null}
          </Callout>
        </div>
      ) : null}

      {jobId ? (
        <div className="mt-5">
          <JobMonitor jobId={jobId} onDone={onDone} />
        </div>
      ) : null}
    </Section>
  );
}
