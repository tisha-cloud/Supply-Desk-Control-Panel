"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import {
  ArrowLeft,
  BadgeCheck,
  ImagePlus,
  Plus,
  Save,
  Star,
  Trash2,
} from "lucide-react";
import { SUPPLY_TYPES, SUPPLY_TONE, supplyLabel, type SupplyTypeValue } from "@/lib/supply";
import { createClient, imageUrl, isSupabaseConfigured } from "@/lib/supabase/client";
import { indianNumber } from "@/lib/format";
import { SplitBar } from "@/components/charts";
import { SetupNotice } from "@/components/SetupNotice";
import {
  Callout,
  EmptyState,
  PageHeader,
  Section,
  Spinner,
  Tag,
  useToast,
} from "@/components/ui";
import type { BuildingWithRelations, MicroMarket, Organisation, Space } from "@/lib/types";

const SELECT =
  "*, micro_markets(code, name), " +
  "developer:organisations!buildings_developer_id_fkey(id, name), " +
  "operator:organisations!buildings_operator_id_fkey(id, name), " +
  "spaces(*), building_images(*), contacts(*)";

interface Reference {
  markets: MicroMarket[];
  organisations: Organisation[];
}

async function loadBuilding(id: string): Promise<BuildingWithRelations> {
  const supabase = createClient();
  const { data, error } = await supabase.from("buildings").select(SELECT).eq("id", id).single();
  if (error) throw new Error(error.message);
  return data as unknown as BuildingWithRelations;
}

async function loadReference(): Promise<Reference> {
  const supabase = createClient();
  const [markets, organisations] = await Promise.all([
    supabase.from("micro_markets").select("*").order("code"),
    supabase.from("organisations").select("*").order("name"),
  ]);
  return {
    markets: (markets.data ?? []) as MicroMarket[],
    organisations: (organisations.data ?? []) as Organisation[],
  };
}

const FIELD_GROUPS: { legend: string; fields: { key: string; label: string; wide?: boolean }[] }[] = [
  {
    legend: "Identity",
    fields: [
      { key: "name", label: "Building name", wide: true },
      { key: "address", label: "Address", wide: true },
      { key: "locality", label: "Locality" },
      { key: "city", label: "City" },
    ],
  },
  {
    legend: "Physical",
    fields: [
      { key: "structure", label: "Structure" },
      { key: "total_size_sqft", label: "Total size (sq ft)" },
      { key: "avg_floor_plate_sqft", label: "Average floor plate (sq ft)" },
      { key: "floor_plate_efficiency", label: "Floor plate efficiency" },
      { key: "power_kva", label: "Power (kVA)" },
      { key: "power_backup", label: "Power back-up" },
      { key: "car_parking_ratio", label: "Car parking ratio" },
    ],
  },
  {
    legend: "Reference",
    fields: [
      { key: "report_period", label: "Report period" },
      { key: "latitude", label: "Latitude" },
      { key: "longitude", label: "Longitude" },
    ],
  },
];

const NUMERIC = ["total_size_sqft", "avg_floor_plate_sqft", "latitude", "longitude"];

export default function BuildingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const isNew = id === "new";
  const router = useRouter();
  const toast = useToast();
  const configured = isSupabaseConfigured();

  const { data: building, error, isLoading, mutate } = useSWR<BuildingWithRelations>(
    configured && !isNew ? ["building", id] : null,
    () => loadBuilding(id),
  );
  const { data: reference } = useSWR<Reference>(configured ? "reference" : null, loadReference);

  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const dirty = Object.keys(draft).length > 0;

  // Ctrl/Cmd+S saves, and leaving with unsaved edits asks first. Both matter
  // on a page where most edits are typed into a long form.
  const saveRef = useCallback(() => {
    if (dirty || isNew) void saveDraft();
  }, [dirty, isNew]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveRef();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [saveRef]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (!configured) {
    return (
      <>
        <PageHeader title="Building" />
        <SetupNotice />
      </>
    );
  }

  const value = (key: string): string => {
    if (key in draft) return String(draft[key] ?? "");
    const current = (building as unknown as Record<string, unknown>)?.[key];
    return current === null || current === undefined ? "" : String(current);
  };

  const setValue = (key: string, next: string) =>
    setDraft((prev) => ({ ...prev, [key]: next === "" ? null : next }));

  async function saveDraft() {
    setSaving(true);
    const supabase = createClient();
    const payload: Record<string, unknown> = { ...draft };
    for (const key of NUMERIC) {
      if (key in payload && payload[key] !== null) payload[key] = Number(payload[key]);
    }

    try {
      if (isNew) {
        if (!payload.name) throw new Error("A building needs a name.");
        const { data, error: insertError } = await supabase
          .from("buildings")
          .insert(payload)
          .select("id")
          .single();
        if (insertError) throw new Error(insertError.message);
        toast({ tone: "success", message: "Building created." });
        router.push(`/data/${data.id}`);
        return;
      }
      if (Object.keys(payload).length === 0) {
        toast({ tone: "info", message: "Nothing to save." });
        return;
      }
      const { error: updateError } = await supabase.from("buildings").update(payload).eq("id", id);
      if (updateError) throw new Error(updateError.message);
      setDraft({});
      toast({ tone: "success", message: "Changes saved." });
      mutate();
    } catch (err) {
      toast({
        tone: "danger",
        title: "Save failed",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setSaving(false);
    }
  }

  async function uploadImages(files: FileList) {
    if (!building) return;
    setSaving(true);
    const supabase = createClient();
    try {
      for (const file of Array.from(files)) {
        const safe = file.name.replace(/[^a-zA-Z0-9._-]/g, "_");
        const path = `buildings/${building.id}/manual-${Date.now()}-${safe}`;
        const { error: uploadError } = await supabase.storage
          .from("building-images")
          .upload(path, file, { upsert: true, contentType: file.type });
        if (uploadError) throw new Error(uploadError.message);

        await supabase.from("building_images").insert({
          building_id: building.id,
          storage_path: path,
          kind: "perspective",
          bytes: file.size,
          is_primary: building.building_images.length === 0,
          sort_order: building.building_images.length,
        });
      }
      toast({ tone: "success", message: `${files.length} image(s) uploaded.` });
      mutate();
    } catch (err) {
      toast({
        tone: "danger",
        title: "Upload failed",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setSaving(false);
    }
  }

  async function makePrimary(imageId: string) {
    if (!building) return;
    const supabase = createClient();
    // The unique index allows one primary per building, so clear first.
    await supabase.from("building_images").update({ is_primary: false }).eq("building_id", building.id);
    await supabase.from("building_images").update({ is_primary: true }).eq("id", imageId);
    mutate();
  }

  async function deleteImage(imageId: string, storagePath: string) {
    const supabase = createClient();
    await supabase.storage.from("building-images").remove([storagePath]);
    await supabase.from("building_images").delete().eq("id", imageId);
    toast({ tone: "info", message: "Image removed." });
    mutate();
  }

  async function addContact() {
    if (!building) return;
    const supabase = createClient();
    await supabase.from("contacts").insert({ building_id: building.id, name: "New contact" });
    mutate();
  }

  async function saveContact(contactId: string, patch: Record<string, string | null>) {
    const supabase = createClient();
    await supabase.from("contacts").update(patch).eq("id", contactId);
    mutate();
  }

  async function deleteContact(contactId: string) {
    const supabase = createClient();
    await supabase.from("contacts").delete().eq("id", contactId);
    mutate();
  }

  async function deleteBuilding() {
    if (!building) return;
    if (!window.confirm(
      `Delete "${building.name}"? Its spaces, photographs and contacts go too. This cannot be undone.`
    )) return;
    const supabase = createClient();
    const { error: deleteError } = await supabase.from("buildings").delete().eq("id", building.id);
    if (deleteError) {
      toast({ tone: "danger", title: "Could not delete", message: deleteError.message });
      return;
    }
    toast({ tone: "success", message: `${building.name} deleted.` });
    router.push("/data");
  }

  async function saveSpace(space: Space, patch: Partial<Space>) {
    const supabase = createClient();
    await supabase.from("spaces").update(patch).eq("id", space.id);
    mutate();
  }

  async function addSpace() {
    if (!building) return;
    const supabase = createClient();
    await supabase
      .from("spaces")
      .insert({ building_id: building.id, floor_label: "New floor", occupancy: "available" });
    mutate();
  }

  async function deleteSpace(spaceId: string) {
    const supabase = createClient();
    await supabase.from("spaces").delete().eq("id", spaceId);
    mutate();
  }

  if (!isNew && isLoading) return <Spinner label="Loading building…" />;

  if (!isNew && error) {
    return (
      <EmptyState title="Could not load this building">{(error as Error).message}</EmptyState>
    );
  }


  const availableSqft =
    building?.spaces
      .filter((s) => s.occupancy === "available")
      .reduce((sum, s) => sum + Number(s.area_sqft ?? 0), 0) ?? 0;
  const occupiedSqft =
    building?.spaces
      .filter((s) => s.occupancy === "occupied")
      .reduce((sum, s) => sum + Number(s.area_sqft ?? 0), 0) ?? 0;

  return (
    <>
      <Link href="/data" className="btn-ghost mb-3 -ml-2">
        <ArrowLeft className="h-4 w-4" aria-hidden />
        Supply database
      </Link>

      <PageHeader
        title={isNew ? "New building" : (building?.name ?? "Building")}
        description={
          isNew
            ? "Add a building by hand. Extraction and workbook import write into the same table."
            : undefined
        }
        actions={
          <>
            {dirty ? (
              <span className="chip bg-warning-soft text-warning">unsaved changes</span>
            ) : null}
            <button
              className="btn-primary"
              onClick={saveDraft}
              disabled={saving || (!dirty && !isNew)}
              title="Ctrl+S"
            >
              <Save className="h-4 w-4" aria-hidden />
              {saving ? "Saving…" : isNew ? "Create building" : dirty ? "Save changes" : "Saved"}
            </button>
          </>
        }
      />

      {!isNew && building ? (
        <div className="mb-6 flex flex-wrap items-center gap-2">
          {building.micro_markets?.code ? <Tag>{building.micro_markets.code}</Tag> : null}
          {building.developer?.name || building.operator?.name ? (
            <Tag>{building.developer?.name ?? building.operator?.name}</Tag>
          ) : null}
          <span className={`chip ${SUPPLY_TONE[building.supply_type] ?? ""}`}>
            {supplyLabel(building.supply_type)}
          </span>
          {building.operator_brand ? <Tag>{building.operator_brand}</Tag> : null}
          {building.is_verified ? (
            <span className="chip bg-positive-soft text-positive">
              <BadgeCheck className="h-3 w-3" aria-hidden />
              verified
            </span>
          ) : null}
        </div>
      ) : null}

      {building?.total_size_is_estimated ? (
        <div className="mb-6">
          <Callout tone="warning" title="Total size was reconstructed, not stated">
            {building.total_size_basis ||
              "No source document stated this building's size; it was derived from floor plate and structure."}
          </Callout>
        </div>
      ) : null}

      {/* -------------------------------------------------------- details */}
      <Section title="Details" className="mb-5">
        <div className="space-y-6">
          {FIELD_GROUPS.map((group) => (
            <fieldset key={group.legend}>
              <legend className="eyebrow mb-3">{group.legend}</legend>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {group.fields.map((field) => (
                  <div key={field.key} className={field.wide ? "sm:col-span-2" : ""}>
                    <label className="label" htmlFor={field.key}>
                      {field.label}
                    </label>
                    <input
                      id={field.key}
                      className="field"
                      value={value(field.key)}
                      onChange={(e) => setValue(field.key, e.target.value)}
                    />
                  </div>
                ))}
              </div>
            </fieldset>
          ))}

          <fieldset>
            <legend className="eyebrow mb-3">Classification</legend>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <div className="sm:col-span-2 lg:col-span-3">
                <span className="label">Category</span>
                <div className="flex flex-wrap gap-2">
                  {SUPPLY_TYPES.map((type) => {
                    const current = value("supply_type") || "conventional";
                    const active = current === type.value;
                    return (
                      <button
                        key={type.value}
                        type="button"
                        aria-pressed={active}
                        onClick={() => setValue("supply_type", type.value)}
                        className={`rounded-lg border px-3 py-2 text-left transition-colors ${
                          active
                            ? "border-accent bg-accent-soft text-accent"
                            : "border-border hover:border-border-strong hover:bg-surface-2"
                        }`}
                      >
                        <span className="block text-sm font-medium">{type.label}</span>
                        <span className="mt-0.5 block text-xs text-ink-3">{type.hint}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
              <div>
                <label className="label" htmlFor="micro_market_id">
                  Micro-market
                </label>
                <select
                  id="micro_market_id"
                  className="field"
                  value={value("micro_market_id")}
                  onChange={(e) => setValue("micro_market_id", e.target.value)}
                >
                  <option value="">—</option>
                  {(reference?.markets ?? []).map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.code}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label" htmlFor="developer_id">
                  Developer / landlord
                </label>
                <select
                  id="developer_id"
                  className="field"
                  value={value("developer_id")}
                  onChange={(e) => setValue("developer_id", e.target.value)}
                >
                  <option value="">—</option>
                  {(reference?.organisations ?? []).map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="sm:col-span-2 lg:col-span-3">
                <label className="label" htmlFor="building_details">
                  Building details
                </label>
                <textarea
                  id="building_details"
                  rows={3}
                  className="field resize-y"
                  value={value("building_details")}
                  onChange={(e) => setValue("building_details", e.target.value)}
                />
              </div>
              <label className="flex cursor-pointer items-center gap-2.5 rounded-lg border border-border p-3 text-sm transition-colors hover:bg-surface-2">
                <input
                  type="checkbox"
                  checked={
                    "is_verified" in draft
                      ? Boolean(draft.is_verified)
                      : Boolean(building?.is_verified)
                  }
                  onChange={(e) => setDraft((prev) => ({ ...prev, is_verified: e.target.checked }))}
                />
                <span className="font-medium">Checked by a human</span>
              </label>
            </div>
          </fieldset>
        </div>
      </Section>

      {!isNew && building ? (
        <>
          {/* ------------------------------------------------ availability */}
          <Section
            title="Availability"
            description="One row per floor for conventional stock, or per offered option for managed office."
            actions={
              <button className="btn-secondary btn-sm" onClick={addSpace}>
                <Plus className="h-3.5 w-3.5" aria-hidden />
                Add row
              </button>
            }
            className="mb-5"
          >
            {building.spaces.length === 0 ? (
              <p className="py-6 text-center text-sm text-ink-3">
                No availability recorded for this building.
              </p>
            ) : (
              <>
                {availableSqft + occupiedSqft > 0 ? (
                  <div className="mb-5">
                    <SplitBar
                      primaryLabel="Available"
                      primaryValue={availableSqft}
                      restLabel="Occupied"
                      restValue={occupiedSqft}
                    />
                    {building.total_size_sqft ? (
                      <p className="mt-2 text-xs text-ink-3">
                        Building total {indianNumber(building.total_size_sqft)} Sft
                      </p>
                    ) : null}
                  </div>
                ) : null}

                <div className="table-scroll -mx-2">
                  <table className="w-full min-w-[860px]">
                    <thead>
                      <tr className="border-b border-border">
                        <th className="th">Floor</th>
                        <th className="th">Operator</th>
                        <th className="th text-right">Area</th>
                        <th className="th text-right">Seats</th>
                        <th className="th">Condition</th>
                        <th className="th">Timeline</th>
                        <th className="th">Status</th>
                        <th className="th text-right">Rent / Seat</th>
                        <th className="th w-10" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {building.spaces
                        .slice()
                        .sort((a, b) => (a.floor_label ?? "").localeCompare(b.floor_label ?? ""))
                        .map((space) => (
                          <tr key={space.id}>
                            <td className="td">
                              <input
                                className="field field-sm"
                                defaultValue={space.floor_label ?? ""}
                                onBlur={(e) => saveSpace(space, { floor_label: e.target.value })}
                              />
                              {space.is_derived ? (
                                <span
                                  className="mt-1 inline-block text-[11px] text-warning"
                                  title={space.derivation_note ?? ""}
                                >
                                  derived
                                </span>
                              ) : null}
                            </td>
                            <td className="td">
                              <select
                                className="field field-sm"
                                aria-label="Operator"
                                defaultValue={space.operator_id ?? ""}
                                onChange={(e) =>
                                  saveSpace(space, {
                                    operator_id: e.target.value || null,
                                  } as Partial<Space>)
                                }
                              >
                                <option value="">—</option>
                                {(reference?.organisations ?? []).map((o) => (
                                  <option key={o.id} value={o.id}>
                                    {o.name}
                                  </option>
                                ))}
                              </select>
                              {space.operator_brand ? (
                                <span className="mt-0.5 block text-[11px] text-ink-3">
                                  {space.operator_brand}
                                </span>
                              ) : null}
                            </td>
                            <td className="td">
                              <input
                                className="field field-sm text-right tabular-nums"
                                defaultValue={space.area_sqft ?? ""}
                                onBlur={(e) =>
                                  saveSpace(space, {
                                    area_sqft: e.target.value ? Number(e.target.value) : null,
                                  })
                                }
                              />
                            </td>
                            <td className="td">
                              <input
                                className="field field-sm text-right tabular-nums"
                                defaultValue={space.seats ?? ""}
                                onBlur={(e) =>
                                  saveSpace(space, {
                                    seats: e.target.value ? Number(e.target.value) : null,
                                  })
                                }
                              />
                            </td>
                            <td className="td">
                              <input
                                className="field field-sm"
                                defaultValue={space.condition ?? ""}
                                onBlur={(e) => saveSpace(space, { condition: e.target.value })}
                              />
                            </td>
                            <td className="td">
                              <input
                                className="field field-sm"
                                defaultValue={space.timeline ?? ""}
                                onBlur={(e) => saveSpace(space, { timeline: e.target.value })}
                              />
                            </td>
                            <td className="td">
                              <select
                                className="field field-sm"
                                defaultValue={space.occupancy}
                                onChange={(e) =>
                                  saveSpace(space, {
                                    occupancy: e.target.value as Space["occupancy"],
                                  })
                                }
                              >
                                <option value="available">available</option>
                                <option value="occupied">occupied</option>
                                <option value="unknown">unknown</option>
                              </select>
                            </td>
                            <td className="td">
                              <input
                                className="field field-sm text-right tabular-nums"
                                aria-label={space.price_per_seat != null ? "Price per seat" : "Rent per sq ft"}
                                title={
                                  space.price_per_seat != null
                                    ? "Per seat, per month"
                                    : "Per sq ft, per month"
                                }
                                defaultValue={space.price_per_seat ?? space.rent_psf ?? ""}
                                onBlur={(e) => {
                                  const next = e.target.value ? Number(e.target.value) : null;
                                  saveSpace(
                                    space,
                                    space.price_per_seat != null || (space.seats ?? 0) > 0
                                      ? { price_per_seat: next }
                                      : { rent_psf: next },
                                  );
                                }}
                              />
                            </td>
                            <td className="td">
                              <button
                                className="btn-ghost px-2"
                                aria-label={`Delete ${space.floor_label ?? "row"}`}
                                onClick={() => deleteSpace(space.id)}
                              >
                                <Trash2 className="h-4 w-4" aria-hidden />
                              </button>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </Section>

          {/* ---------------------------------------------------- images */}
          <Section
            title={`Photographs (${building.building_images.length})`}
            actions={
              <label className="btn-secondary btn-sm cursor-pointer">
                <ImagePlus className="h-3.5 w-3.5" aria-hidden />
                Add images
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  className="sr-only"
                  onChange={(e) => e.target.files && uploadImages(e.target.files)}
                />
              </label>
            }
            className="mb-5"
          >
            {building.building_images.length === 0 ? (
              <p className="py-6 text-center text-sm text-ink-3">
                None yet. Images imported from the workbook appear here automatically.
              </p>
            ) : (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {building.building_images
                  .slice()
                  .sort(
                    (a, b) =>
                      Number(b.is_primary) - Number(a.is_primary) || a.sort_order - b.sort_order,
                  )
                  .map((image) => (
                    <figure
                      key={image.id}
                      className="group relative overflow-hidden rounded-lg border border-border bg-surface-2"
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={imageUrl(image.storage_path)}
                        alt={image.caption ?? building.name}
                        className="aspect-4/3 w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
                        loading="lazy"
                      />
                      {image.is_primary ? (
                        <span
                          className="chip absolute top-2 left-2 text-white"
                          style={{ background: "var(--accent)" }}
                        >
                          primary
                        </span>
                      ) : null}
                      <div className="absolute inset-x-0 bottom-0 flex justify-end gap-1.5 bg-gradient-to-t from-black/70 to-transparent p-2 opacity-0 transition-opacity group-hover:opacity-100">
                        {!image.is_primary ? (
                          <button
                            className="grid h-7 w-7 place-items-center rounded-md bg-white/95 text-black transition-transform hover:scale-105"
                            aria-label="Make primary"
                            title="Make primary"
                            onClick={() => makePrimary(image.id)}
                          >
                            <Star className="h-3.5 w-3.5" aria-hidden />
                          </button>
                        ) : null}
                        <button
                          className="grid h-7 w-7 place-items-center rounded-md bg-white/95 transition-transform hover:scale-105"
                          style={{ color: "var(--danger)" }}
                          aria-label="Delete image"
                          title="Delete image"
                          onClick={() => deleteImage(image.id, image.storage_path)}
                        >
                          <Trash2 className="h-3.5 w-3.5" aria-hidden />
                        </button>
                      </div>
                    </figure>
                  ))}
              </div>
            )}
          </Section>

          {/* -------------------------------------------------- contacts */}
          <Section
            title="Contacts"
            actions={
              <button className="btn-secondary btn-sm" onClick={addContact}>
                <Plus className="h-3.5 w-3.5" aria-hidden />
                Add contact
              </button>
            }
            className="mb-5"
          >
            {building.contacts.length === 0 ? (
              <p className="py-6 text-center text-sm text-ink-3">
                No contacts recorded. Add one, or import them with a workbook.
              </p>
            ) : (
              <div className="table-scroll -mx-2">
                <table className="w-full min-w-[720px]">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="th">Name</th>
                      <th className="th">Designation</th>
                      <th className="th">Phone</th>
                      <th className="th">Email</th>
                      <th className="th w-10" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {building.contacts.map((contact) => (
                      <tr key={contact.id}>
                        {(
                          [
                            ["name", contact.name],
                            ["designation", contact.designation],
                            ["phone", contact.phone],
                            ["email", contact.email],
                          ] as [string, string | null][]
                        ).map(([field, current]) => (
                          <td key={field} className="td">
                            <input
                              className="field field-sm"
                              aria-label={field}
                              defaultValue={current ?? ""}
                              onBlur={(e) =>
                                saveContact(contact.id, { [field]: e.target.value || null })
                              }
                            />
                          </td>
                        ))}
                        <td className="td">
                          <button
                            className="btn-ghost px-2"
                            aria-label={`Delete ${contact.name ?? "contact"}`}
                            onClick={() => deleteContact(contact.id)}
                          >
                            <Trash2 className="h-4 w-4" aria-hidden />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>

          {/* --------------------------------------------------- danger zone */}
          <Section title="Delete this building">
            <p className="mb-4 text-sm text-ink-2">
              Removes the building and everything attached to it — availability rows,
              photographs and contacts. This cannot be undone.
            </p>
            <button className="btn-danger" onClick={deleteBuilding}>
              <Trash2 className="h-4 w-4" aria-hidden />
              Delete {building.name}
            </button>
          </Section>
        </>
      ) : null}
    </>
  );
}
