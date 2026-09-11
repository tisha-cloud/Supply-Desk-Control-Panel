"use client";

import { useRef, useState } from "react";
import { MapPin, Upload, Users, X } from "lucide-react";
import { backend, BackendError } from "@/lib/backend";
import { Callout, Section, useToast } from "@/components/ui";
import type { DemographyProfile } from "@/lib/types";

/**
 * Which micro-market a workforce should sit in, argued from where they live.
 *
 * The client hands over employee pincodes; this ranks the markets the desk
 * trades by how many of them live beside each. Ranking is by headcount rather
 * than by average distance on purpose: the geographic midpoint between two
 * clusters suits neither of them.
 *
 * Every pincode is shown with the locality it was read as, and anything
 * unrecognised is reported rather than dropped - a silent drop would move the
 * majority without anyone noticing.
 */
export function DemographyPanel({
  onUseMarket,
}: {
  onUseMarket: (market: string) => void;
}) {
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement>(null);

  const [text, setText] = useState("");
  const [profile, setProfile] = useState<DemographyProfile | null>(null);
  const [busy, setBusy] = useState(false);

  function fail(err: unknown) {
    toast({
      tone: "danger",
      title: "Could not read those pincodes",
      message: err instanceof BackendError ? err.message : String(err),
    });
  }

  async function analyse() {
    if (!text.trim()) return;
    setBusy(true);
    try {
      setProfile(await backend.profileDemography({ text }));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function analyseFile(file: File) {
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch("/api/backend/api/demography/upload", {
        method: "POST",
        body: form,
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Upload failed");
      setProfile(body as DemographyProfile);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  return (
    <Section
      title="Demography profiling"
      description="Paste or upload the employee pincodes and this ranks the micro-markets by how many of them live nearest, so the location is argued from commutes rather than from available stock."
      className="mb-5"
    >
      <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
        <div>
          <label className="label" htmlFor="pincodes">
            Employee pincodes
          </label>
          <textarea
            id="pincodes"
            rows={4}
            className="field resize-y font-mono text-sm"
            placeholder={"560102\n560034\n560068, 560103, 560102"}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <p className="mt-2 text-xs text-ink-3">
            One per employee, in any shape — a pasted column, commas, or a whole
            spreadsheet. Repeats count, because one row is one person.
          </p>
        </div>

        <div className="flex flex-col justify-end gap-2">
          <button
            className="btn-primary justify-center"
            onClick={analyse}
            disabled={!text.trim() || busy}
          >
            <Users className="h-4 w-4" aria-hidden />
            {busy ? "Reading…" : "Find the best location"}
          </button>
          <button
            className="btn-secondary justify-center"
            onClick={() => fileInput.current?.click()}
            disabled={busy}
          >
            <Upload className="h-4 w-4" aria-hidden />
            Upload employee list
          </button>
          <input
            ref={fileInput}
            type="file"
            accept=".xlsx,.xls,.csv,.txt"
            className="sr-only"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) analyseFile(file);
            }}
          />
          <p className="text-center text-xs text-ink-3">.xlsx · .csv · .txt</p>
        </div>
      </div>

      {profile ? (
        <div className="mt-5">
          {profile.recommended ? (
            <Callout tone="success" title={`Best located in ${profile.recommended}`}>
              {profile.recommended_share}% of the {profile.total_employees} employees live
              nearest {profile.recommended}.{" "}
              <button
                className="font-medium underline underline-offset-2"
                onClick={() => onUseMarket(profile.recommended!)}
              >
                Use it in the requirement
              </button>
            </Callout>
          ) : (
            <Callout tone="warning" title="No market with stock matched">
              None of the recognised pincodes sit beside a micro-market the database has
              buildings in.
            </Callout>
          )}

          <div className="card table-scroll mt-4 overflow-hidden">
            <table className="w-full min-w-[680px]">
              <thead className="bg-surface-2">
                <tr>
                  <th className="th">Micro-market</th>
                  <th className="th text-right">Employees</th>
                  <th className="th text-right">Share</th>
                  <th className="th text-right">Buildings</th>
                  <th className="th">Where they live</th>
                  <th className="th w-10" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {profile.markets.map((market) => (
                  <tr key={market.micro_market} className={market.buildings ? "" : "opacity-55"}>
                    <td className="td font-medium">
                      <span className="inline-flex items-center gap-1.5">
                        <MapPin className="h-3.5 w-3.5 text-ink-3" aria-hidden />
                        {market.micro_market}
                      </span>
                    </td>
                    <td className="td text-right tabular-nums">{market.employees}</td>
                    <td className="td text-right tabular-nums">{market.share}%</td>
                    <td className="td text-right tabular-nums">
                      {market.buildings || (
                        <span className="text-xs text-warning">no stock</span>
                      )}
                    </td>
                    <td className="td text-xs text-ink-2">
                      {market.areas
                        .slice(0, 3)
                        .map((a) => `${a.locality} (${a.employees})`)
                        .join(", ")}
                      {market.areas.length > 3 ? ` +${market.areas.length - 3} more` : ""}
                    </td>
                    <td className="td">
                      {market.buildings ? (
                        <button
                          className="btn-ghost btn-sm text-xs"
                          onClick={() => onUseMarket(market.micro_market)}
                        >
                          Use
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {profile.unrecognised.length > 0 ? (
            <p className="mt-3 flex items-start gap-2 text-xs text-warning">
              <X className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              {profile.unrecognised_employees} of {profile.total_employees} not recognised as
              Bengaluru pincodes and excluded from the ranking:{" "}
              {profile.unrecognised
                .slice(0, 8)
                .map((u) => `${u.pincode} (${u.employees})`)
                .join(", ")}
              {profile.unrecognised.length > 8 ? " …" : ""}
            </p>
          ) : null}
        </div>
      ) : null}
    </Section>
  );
}
