"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import {
  Download,
  FileSpreadsheet,
  Presentation,
  RotateCcw,
  Sparkles,
  Undo2,
  X,
} from "lucide-react";
import { backend, BackendError } from "@/lib/backend";
import { indianNumber } from "@/lib/format";
import { MANAGED_SEAT_THRESHOLD, supplyLabel, supplyTone } from "@/lib/supply";
import {
  Callout,
  EmptyState,
  PageHeader,
  Section,
  Spinner,
  Tag,
  useToast,
} from "@/components/ui";
import type { DeckFormat, DeckPreview, DeckPreviewBuilding } from "@/lib/types";

const EXAMPLES = [
  "30,000 sq ft warm shell on ORR, ready to move in",
  "150 managed seats in Koramangala or Indiranagar",
  "8 desks in HSR for a small team",
  "Fully furnished floor in the CBD under ₹150 per sq ft",
];

/** One produced file. Both formats can be made from the same shortlist. */
interface Output {
  filename: string;
  format: DeckFormat;
  options: number;
}

export default function DecksPage() {
  const toast = useToast();

  const [query, setQuery] = useState("");
  const [clientName, setClientName] = useState("");
  const [template, setTemplate] = useState("");
  const [preview, setPreview] = useState<DeckPreview | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [outputs, setOutputs] = useState<Output[]>([]);
  const [busy, setBusy] = useState<"preview" | DeckFormat | null>(null);

  const { data: templates } = useSWR("templates", () => backend.templates(), {
    shouldRetryOnError: false,
  });
  const { data: health } = useSWR("backend-health", () => backend.health(), {
    shouldRetryOnError: false,
  });

  async function runPreview() {
    if (!query.trim()) return;
    setBusy("preview");
    setOutputs([]);
    try {
      const matched = await backend.previewDeck({ query });
      setPreview(matched);
      // A fresh shortlist starts fully selected: the picks the model made are
      // the default, and editing them is the reviewer opting out of one.
      setChosen(matched.buildings.map((b) => b.id));
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

  async function build(format: DeckFormat) {
    if (!query.trim() || chosen.length === 0) return;
    setBusy(format);
    try {
      const result = await backend.generateDeck({
        query,
        client_name: clientName.trim() || "Valued Client",
        template_name: format === "pptx" ? template || null : null,
        building_ids: chosen,
        output_format: format,
      });
      // Replace any earlier file of the same format; keep the other one, so
      // making both a deck and a sheet leaves both links on screen.
      setOutputs((prev) => [
        ...prev.filter((o) => o.format !== format),
        { filename: result.filename, format, options: result.options },
      ]);
      toast({
        tone: "success",
        title: format === "pptx" ? "Proposal ready" : "Spreadsheet ready",
        message: `${result.options} option${result.options === 1 ? "" : "s"} included.`,
      });
    } catch (err) {
      toast({
        tone: "danger",
        title: "Could not build the file",
        message: err instanceof BackendError ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }

  function remove(id: string) {
    setChosen((prev) => prev.filter((x) => x !== id));
  }

  function restore(id: string) {
    setChosen((prev) => [...prev, id]);
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

  const byId = useMemo(
    () => new Map((preview?.buildings ?? []).map((b) => [b.id, b])),
    [preview],
  );
  const included = chosen
    .map((id) => byId.get(id))
    .filter(Boolean) as DeckPreviewBuilding[];
  const dropped = (preview?.buildings ?? []).filter((b) => !chosen.includes(b.id));

  // Everything the model inferred, minus the keys the page renders itself.
  const criteriaTags = preview
    ? Object.entries(preview.criteria).filter(
        ([key, v]) =>
          !["title", "limit", "product", "product_label", "product_note"].includes(key) &&
          v !== null &&
          v !== undefined &&
          v !== "" &&
          (!Array.isArray(v) || v.length),
      )
    : [];

  return (
    <>
      <PageHeader
        eyebrow="Client output"
        title="Proposal Builder"
        description="Describe the requirement in plain English. The model turns it into filters and picks the options; you edit the shortlist, then take it as a PowerPoint proposal or an Excel grid."
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
              Template <span className="font-normal text-ink-3">(PowerPoint only)</span>
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

        <div className="mt-5">
          <button
            className="btn-primary"
            onClick={runPreview}
            disabled={!query.trim() || busy !== null}
          >
            <Sparkles className="h-4 w-4" aria-hidden />
            {busy === "preview" ? "Matching…" : preview ? "Match again" : "Find options"}
          </button>
        </div>
      </Section>

      {busy === "preview" ? (
        <Spinner label="Querying the database…" />
      ) : preview ? (
        <div className="mt-8">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="font-semibold tracking-tight">
              {preview.count} option{preview.count === 1 ? "" : "s"} matched
              {preview.required && preview.meets < preview.count ? (
                <span className="ml-2 text-sm font-normal text-ink-3">
                  {preview.meets} meet the requirement, {preview.count - preview.meets} fall
                  short
                </span>
              ) : null}
            </h2>
            <p className="text-sm text-ink-3">
              Every match is listed. Remove what you do not want, reorder with the arrows,
              then pick a format.
            </p>
          </div>

          {preview.product_note ? (
            <div className="mb-4">
              <Callout tone="info" title={`Quoted as ${preview.product_label}`}>
                {preview.product_note} Managed and co-working are one listing, so the shortlist
                is drawn from all of it — only the wording changes, at{" "}
                {MANAGED_SEAT_THRESHOLD} seats.
              </Callout>
            </div>
          ) : null}

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
                <table className="w-full min-w-[1060px]">
                  <thead className="bg-surface-2">
                    <tr>
                      <th className="th w-16">Order</th>
                      <th className="th">Building</th>
                      <th className="th">Operator / Landlord</th>
                      <th className="th">Market</th>
                      <th className="th">Category</th>
                      <th className="th text-right">Available</th>
                      <th className="th">Fit</th>
                      <th className="th text-right">Price</th>
                      <th className="th">Condition</th>
                      <th className="th">Timeline</th>
                      <th className="th w-10" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {included.map((building, index) => (
                      <tr key={building.id}>
                        <td className="td">
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
                                disabled={index === included.length - 1}
                                onClick={() => move(building.id, 1)}
                              >
                                ▼
                              </button>
                            </span>
                          </div>
                        </td>
                        <td className="td font-medium">
                          {building.name}
                          {building.photos === 0 ? (
                            <span className="ml-2 text-xs font-normal text-warning">
                              no photo
                            </span>
                          ) : null}
                        </td>
                        <td className="td text-ink-2">{building.landlord || "—"}</td>
                        <td className="td">
                          {building.micro_market ? <Tag>{building.micro_market}</Tag> : "—"}
                        </td>
                        <td className="td">
                          <span className={`chip ${supplyTone(building.supply_type)}`}>
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
                        <td className="td">
                          {building.fit === "meets" ? (
                            <span className="chip bg-positive-soft text-positive">fits</span>
                          ) : building.fit === "short" ? (
                            <span
                              className="chip bg-warning-soft text-warning"
                              title={`Short of the requirement by ${indianNumber(
                                building.shortfall,
                              )} ${preview.required_unit === "area" ? "sq ft" : "seats"}`}
                            >
                              short {indianNumber(building.shortfall)}
                            </span>
                          ) : (
                            <span className="text-xs text-ink-3">—</span>
                          )}
                        </td>
                        <td className="td text-right tabular-nums">
                          {building.price_per_seat
                            ? `₹${indianNumber(building.price_per_seat)}/seat`
                            : building.rent_psf
                              ? `₹${indianNumber(building.rent_psf)}/sft`
                              : "—"}
                        </td>
                        <td className="td text-ink-2">{building.condition || "—"}</td>
                        <td className="td text-ink-2">{building.timeline || "—"}</td>
                        <td className="td">
                          <button
                            className="btn-ghost btn-sm"
                            aria-label={`Remove ${building.name}`}
                            title="Remove from the proposal"
                            onClick={() => remove(building.id)}
                          >
                            <X className="h-4 w-4" aria-hidden />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {dropped.length > 0 ? (
                <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface-2 p-3">
                  <span className="text-sm text-ink-2">Removed ({dropped.length}):</span>
                  {dropped.map((building) => (
                    <button
                      key={building.id}
                      className="chip border border-border bg-surface text-ink-2 hover:border-accent-border hover:text-accent"
                      onClick={() => restore(building.id)}
                      title="Put this option back"
                    >
                      <Undo2 className="h-3 w-3" aria-hidden />
                      {building.name}
                    </button>
                  ))}
                  <span className="flex-1" />
                  <button
                    className="btn-ghost btn-sm"
                    onClick={() => setChosen(preview.buildings.map((b) => b.id))}
                  >
                    <RotateCcw className="h-3.5 w-3.5" aria-hidden />
                    Restore all
                  </button>
                </div>
              ) : null}

              {/* -------------------------------------------- choose a format */}
              <div className="card mt-5 p-4">
                <p className="mb-3 text-sm text-ink-2">
                  {included.length === 0 ? (
                    <span className="text-warning">
                      Every option has been removed. Put at least one back to build a file.
                    </span>
                  ) : (
                    <>
                      Take {included.length} option{included.length === 1 ? "" : "s"} as:
                    </>
                  )}
                </p>
                <div className="flex flex-wrap gap-2">
                  <button
                    className="btn-primary"
                    onClick={() => build("pptx")}
                    disabled={included.length === 0 || busy !== null}
                  >
                    <Presentation className="h-4 w-4" aria-hidden />
                    {busy === "pptx" ? "Building…" : "PowerPoint proposal"}
                  </button>
                  <button
                    className="btn-secondary"
                    onClick={() => build("xlsx")}
                    disabled={included.length === 0 || busy !== null}
                  >
                    <FileSpreadsheet className="h-4 w-4" aria-hidden />
                    {busy === "xlsx" ? "Building…" : "Excel sheet"}
                  </button>
                </div>
                <p className="mt-3 text-xs text-ink-3">
                  Both are built from the same shortlist, so the figures cannot disagree. Make
                  one, the other, or both.
                </p>
              </div>

              {outputs.length > 0 ? (
                <div className="mt-4 space-y-2">
                  {outputs.map((output) => (
                    <Callout
                      key={output.format}
                      tone="success"
                      title={output.format === "pptx" ? "Proposal ready" : "Spreadsheet ready"}
                    >
                      <p>
                        {output.options} option{output.options === 1 ? "" : "s"} included, every
                        figure taken from the database.
                      </p>
                      <a
                        className="btn-primary mt-3"
                        href={`/api/backend/api/decks/download/${encodeURIComponent(output.filename)}`}
                      >
                        <Download className="h-4 w-4" aria-hidden />
                        Download {output.filename}
                      </a>
                    </Callout>
                  ))}
                </div>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </>
  );
}
