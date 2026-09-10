"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { AlertTriangle, ArrowLeft, CheckCircle2, Merge } from "lucide-react";
import { backend, BackendError } from "@/lib/backend";
import { isSupabaseConfigured } from "@/lib/supabase/client";
import { SetupNotice } from "@/components/SetupNotice";
import {
  Callout,
  EmptyState,
  PageHeader,
  Section,
  TableSkeleton,
  useToast,
} from "@/components/ui";
import type { DuplicateGroup } from "@/lib/types";

export default function OrganisationsPage() {
  const toast = useToast();
  const configured = isSupabaseConfigured();
  const { data, error, isLoading, mutate } = useSWR<DuplicateGroup[]>(
    configured ? "duplicate-organisations" : null,
    () => backend.duplicateOrganisations(),
    { shouldRetryOnError: false },
  );

  // Which records inside each group the reviewer has agreed to fold in.
  const [chosen, setChosen] = useState<Record<string, Set<string>>>({});
  const [working, setWorking] = useState<string | null>(null);

  function selected(group: DuplicateGroup): Set<string> {
    return (
      chosen[group.keep.id] ??
      // Safe groups start fully ticked; anything carrying a risk starts empty,
      // so folding in a possibly-different firm is always a deliberate act.
      new Set(group.confident ? group.merge.map((m) => m.id) : [])
    );
  }

  function toggle(group: DuplicateGroup, id: string) {
    const next = new Set(selected(group));
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChosen((prev) => ({ ...prev, [group.keep.id]: next }));
  }

  async function merge(group: DuplicateGroup) {
    const ids = [...selected(group)];
    if (ids.length === 0) return;
    setWorking(group.keep.id);
    try {
      const result = await backend.mergeOrganisations({
        keep_id: group.keep.id,
        merge_ids: ids,
      });
      toast({
        tone: "success",
        title: `Merged into ${group.keep.name}`,
        message: `${result.buildings} building, ${result.spaces} space and ${result.contacts} contact references moved.`,
      });
      mutate();
    } catch (err) {
      toast({
        tone: "danger",
        title: "Merge failed",
        message: err instanceof BackendError ? err.message : String(err),
      });
    } finally {
      setWorking(null);
    }
  }

  if (!configured) {
    return (
      <>
        <PageHeader title="Duplicate landlords" />
        <SetupNotice />
      </>
    );
  }

  const totalRecords = (data ?? []).reduce((sum, g) => sum + g.merge.length, 0);

  return (
    <>
      <Link href="/data" className="btn-ghost mb-3 -ml-2">
        <ArrowLeft className="h-4 w-4" aria-hidden />
        Supply database
      </Link>

      <PageHeader
        eyebrow="Data quality"
        title="Duplicate landlords and operators"
        description="The supply files name landlords loosely, so one company ends up as several records and a filter finds only part of its stock. Nothing is merged until you confirm it."
      />

      {isLoading ? (
        <TableSkeleton rows={4} />
      ) : error ? (
        <Callout tone="danger" title="Could not load the report">
          {(error as Error).message}
        </Callout>
      ) : !data || data.length === 0 ? (
        <EmptyState icon={CheckCircle2} title="No duplicates found">
          Every landlord and operator appears once.
        </EmptyState>
      ) : (
        <>
          <div className="mb-5">
            <Callout tone="info">
              {data.length} group{data.length === 1 ? "" : "s"} proposed, covering{" "}
              {totalRecords} record{totalRecords === 1 ? "" : "s"} that would be folded away.
              Groups marked <strong>check carefully</strong> differ by more than spelling and
              start unticked.
            </Callout>
          </div>

          <div className="space-y-4">
            {data.map((group) => {
              const picked = selected(group);
              const busy = working === group.keep.id;
              return (
                <Section key={group.keep.id}>
                  <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold">{group.keep.name}</span>
                        <span className="chip bg-surface-2 text-ink-2">
                          {group.keep.buildings} building
                          {group.keep.buildings === 1 ? "" : "s"}
                        </span>
                        {group.confident ? (
                          <span className="chip bg-positive-soft text-positive">
                            <CheckCircle2 className="h-3 w-3" aria-hidden />
                            spelling only
                          </span>
                        ) : (
                          <span className="chip bg-warning-soft text-warning">
                            <AlertTriangle className="h-3 w-3" aria-hidden />
                            check carefully
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-sm text-ink-2">
                        Kept as the surviving record. {group.moves} reference
                        {group.moves === 1 ? "" : "s"} would move onto it.
                      </p>
                    </div>
                    <button
                      className="btn-primary"
                      disabled={busy || picked.size === 0}
                      onClick={() => merge(group)}
                    >
                      <Merge className="h-4 w-4" aria-hidden />
                      {busy
                        ? "Merging…"
                        : `Merge ${picked.size} record${picked.size === 1 ? "" : "s"}`}
                    </button>
                  </div>

                  <ul className="divide-y divide-border">
                    {group.merge.map((candidate) => (
                      <li key={candidate.id} className="flex items-start gap-3 py-3">
                        <input
                          type="checkbox"
                          className="mt-1"
                          aria-label={`Fold ${candidate.name} into ${group.keep.name}`}
                          checked={picked.has(candidate.id)}
                          onChange={() => toggle(group, candidate.id)}
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-medium">{candidate.name}</span>
                            <span className="text-xs text-ink-3 tabular-nums">
                              {candidate.buildings} building
                              {candidate.buildings === 1 ? "" : "s"}
                            </span>
                          </div>
                          {candidate.risk ? (
                            <p className="mt-1 text-xs text-warning">{candidate.risk}</p>
                          ) : null}
                        </div>
                      </li>
                    ))}
                  </ul>
                </Section>
              );
            })}
          </div>
        </>
      )}
    </>
  );
}
