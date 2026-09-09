"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { Download, Presentation, Sparkles, X } from "lucide-react";
import { backend, BackendError } from "@/lib/backend";
import { indianNumber } from "@/lib/format";
import { SUPPLY_TONE, supplyLabel } from "@/lib/supply";
import {
  Callout,
  EmptyState,
  PageHeader,
  Section,
  Spinner,
  Tag,
  useToast,
} from "@/components/ui";
import type { DeckPreviewBuilding } from "@/lib/types";

const EXAMPLES = [
  "30,000 sq ft warm shell on ORR, ready to move in",
  "150 managed seats in Koramangala or Indiranagar",
  "Fully furnished floor in the CBD under ₹150 per sq ft",
  "Campus option in Whitefield above 1 lakh sq ft",
];

interface PreviewState {
  criteria: Record<string, unknown>;
  count: number;
  buildings: DeckPreviewBuilding[];
}

export default function DecksPage() {
  const toast = useToast();

  const [query, setQuery] = useState("");
  const [clientName, setClientName] = useState("");
  const [template, setTemplate] = useState("");
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [result, setResult] = useState<{ filename: string; options: number } | null>(null);
  const [busy, setBusy] = useState<"preview" | "generate" | null>(null);

  const { data: templates } = useSWR("templates", () => backend.templates(), {
    shouldRetryOnError: false,
  });
  const { data: health } = useSWR("backend-health", () => backend.health(), {
    shouldRetryOnError: false,
  });

  // A fresh shortlist starts fully selected - the model's picks are the default.
  useEffect(() => {
    if (preview) setChosen(preview.buildings.map((b) => b.id));
  }, [preview]);

  async function runPreview() {
    if (!query.trim()) return;
    setBusy("preview");
    setResult(null);
    try {
      setPreview(await backend.previewDeck({ query }));
    } catch (err) {
      setPreview(null);
      toast({
        tone: "danger",
        title: "Could not match that requirement",
        message: err instanceof BackendError ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }

  async function runGenerate(useChosen: boolean) {
    if (!query.trim()) return;
    setBusy("generate");
    try {
      const deck = await backend.generateDeck({
        query,
        client_name: clientName.trim() || "Valued Client",
        template_name: template || null,
        ...(useChosen && chosen.length ? { building_ids: chosen } : {}),
      });
      setResult({ filename: deck.filename, options: deck.options });
      toast({ tone: "success", title: "Deck ready", message: `${deck.options} options included.` });
    } catch (err) {
      toast({
        tone: "danger",
        title: "Deck generation failed",
        message: err instanceof BackendError ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }

  function move(id: string, delta: number) {
    setChosen((prev) => {
      const index = prev.indexOf(id);
      const target = index + delta;
      if (index < 0 || target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  const criteriaTags = preview
    ? Object.entries(preview.criteria).filter(
        ([, v]) => v !== null && v !== undefined && v !== "" && (!Array.isArray(v) || v.length),
      )
    : [];

  const ordered = preview
    ? [...preview.buildings].sort((a, b) => {
        const ia = chosen.indexOf(a.id);
        const ib = chosen.indexOf(b.id);
        if (ia === -1 && ib === -1) return 0;
        if (ia === -1) return 1;
        if (ib === -1) return -1;
        return ia - ib;
      })
    : [];

  return (
    <>
      <PageHeader
        eyebrow="Feature 3"
        title="Deck Builder"
        description="Describe the requirement in plain English. The model turns it into filters, the database supplies the buildings, and your options template produces the proposal."
      />

      {health?.llm_provider === "none" ? (
        <div className="mb-6">
          <Callout tone="warning" title="No LLM key configured">
            Requirements are still parsed, but by keyword matching rather than the model. Set a
            key in <code>extraction/.env</code> for better shortlists.
          </Callout>
        </div>
      ) : null}

      <Section>
        <label className="label" htmlFor="requirement">
          Client requirement
        </label>
        <textarea
          id="requirement"
          rows={3}
          className="field resize-y text-base"
          placeholder="e.g. 30,000 sq ft warm shell on ORR, ready to move in, under ₹95 per sq ft"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />

        <div className="mt-3 flex flex-wrap gap-1.5">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="chip border border-border bg-surface-2 text-ink-2 transition-colors hover:border-accent-border hover:bg-accent-soft hover:text-accent"
              onClick={() => setQuery(example)}
            >
              {example}
            </button>
          ))}
        </div>

        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="client">
              Client name
            </label>
            <input
              id="client"
              className="field"
              placeholder="Valued Client"
              value={clientName}
              onChange={(e) => setClientName(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="template">
              Template
            </label>
            <select
              id="template"
              className="field"
              value={template}
              onChange={(e) => setTemplate(e.target.value)}
            >
              <option value="">options format.pptx (default)</option>
              {(templates ?? []).map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          <button className="btn-primary" onClick={runPreview} disabled={!query.trim() || busy !== null}>
            <Sparkles className="h-4 w-4" aria-hidden />
            {busy === "preview" ? "Matching…" : "Find options"}
          </button>
          <button
            className="btn-secondary"
            onClick={() => runGenerate(false)}
            disabled={!query.trim() || busy !== null}
          >
            {busy === "generate" && !preview ? "Building…" : "Skip review, build deck"}
          </button>
        </div>
      </Section>

      {result ? (
        <div className="mt-5">
          <Callout tone="success" title="Proposal ready">
            <p>
              {result.options} option{result.options === 1 ? "" : "s"} included, every figure taken
              from the database.
            </p>
            <a
              className="btn-primary mt-3"
              href={`/api/backend/api/decks/download/${encodeURIComponent(result.filename)}`}
            >
              <Download className="h-4 w-4" aria-hidden />
              Download {result.filename}
            </a>
          </Callout>
        </div>
      ) : null}

      {busy === "preview" ? (
        <Spinner label="Querying the database…" />
      ) : preview ? (
        <div className="mt-8">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="font-semibold tracking-tight">
              {preview.count} option{preview.count === 1 ? "" : "s"} matched
            </h2>
            <p className="text-sm text-ink-3">
              Untick anything you do not want, reorder with the arrows, then build the deck.
            </p>
          </div>

          {criteriaTags.length > 0 ? (
            <div className="mb-4 flex flex-wrap gap-1.5">
              {criteriaTags.map(([key, value]) => (
                <Tag key={key}>
                  <span className="text-ink-3">{key.replace(/_/g, " ")}</span>
                  <span className="font-medium">
                    {Array.isArray(value) ? value.join(", ") : String(value)}
                  </span>
                </Tag>
              ))}
            </div>
          ) : null}

          {preview.buildings.length === 0 ? (
            <EmptyState icon={Presentation} title="Nothing matched">
              Try widening the area or micro-market, or import more supply first.
            </EmptyState>
          ) : (
            <>
              <div className="card table-scroll overflow-hidden">
                <table className="w-full min-w-[820px]">
                  <thead className="bg-surface-2">
                    <tr>
                      <th className="th w-10" />
                      <th className="th w-14">Order</th>
                      <th className="th">Building</th>
                      <th className="th">Operator / Landlord</th>
                      <th className="th">Market</th>
                      <th className="th">Category</th>
                      <th className="th text-right">Available</th>
                      <th className="th text-right">Rent</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {ordered.map((building) => {
                      const index = chosen.indexOf(building.id);
                      const included = index >= 0;
                      return (
                        <tr key={building.id} className={included ? "" : "opacity-45"}>
                          <td className="td">
                            <input
                              type="checkbox"
                              aria-label={`Include ${building.name}`}
                              checked={included}
                              onChange={() =>
                                setChosen((prev) =>
                                  included
                                    ? prev.filter((id) => id !== building.id)
                                    : [...prev, building.id],
                                )
                              }
                            />
                          </td>
                          <td className="td">
                            {included ? (
                              <div className="flex items-center gap-1.5">
                                <span className="w-4 text-xs tabular-nums text-ink-3">
                                  {index + 1}
                                </span>
                                <span className="flex flex-col leading-none">
                                  <button
                                    className="px-1 text-[11px] text-ink-3 hover:text-ink disabled:opacity-25"
                                    aria-label={`Move ${building.name} up`}
                                    disabled={index === 0}
                                    onClick={() => move(building.id, -1)}
                                  >
                                    ▲
                                  </button>
                                  <button
                                    className="px-1 text-[11px] text-ink-3 hover:text-ink disabled:opacity-25"
                                    aria-label={`Move ${building.name} down`}
                                    disabled={index === chosen.length - 1}
                                    onClick={() => move(building.id, 1)}
                                  >
                                    ▼
                                  </button>
                                </span>
                              </div>
                            ) : (
                              <span className="text-xs text-ink-3">—</span>
                            )}
                          </td>
                          <td className="td font-medium">{building.name}</td>
                          <td className="td text-ink-2">{building.landlord || "—"}</td>
                          <td className="td">
                            {building.micro_market ? <Tag>{building.micro_market}</Tag> : "—"}
                          </td>
                          <td className="td">
                            <span className={`chip ${SUPPLY_TONE[building.supply_type] ?? ""}`}>
                              {supplyLabel(building.supply_type)}
                            </span>
                          </td>
                          <td className="td text-right tabular-nums">
                            {building.available_sqft
                              ? `${indianNumber(building.available_sqft)} Sft`
                              : building.available_seats
                                ? `${indianNumber(building.available_seats)} seats`
                                : "—"}
                          </td>
                          <td className="td text-right tabular-nums">
                            {building.rent_psf ? `₹${indianNumber(building.rent_psf)}` : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-3">
                <button
                  className="btn-primary"
                  onClick={() => runGenerate(true)}
                  disabled={chosen.length === 0 || busy !== null}
                >
                  <Presentation className="h-4 w-4" aria-hidden />
                  {busy === "generate"
                    ? "Building proposal…"
                    : `Build proposal with ${chosen.length} option${chosen.length === 1 ? "" : "s"}`}
                </button>
                {chosen.length !== preview.buildings.length ? (
                  <button
                    className="btn-ghost"
                    onClick={() => setChosen(preview.buildings.map((b) => b.id))}
                  >
                    <X className="h-4 w-4" aria-hidden />
                    Reset to the model&rsquo;s picks
                  </button>
                ) : null}
              </div>
            </>
          )}
        </div>
      ) : null}
    </>
  );
}
