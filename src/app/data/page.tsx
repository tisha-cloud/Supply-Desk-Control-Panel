"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import {
  Building2,
  ChevronRight,
  FileSpreadsheet,
  Images,
  Plus,
  Search,
  Trash2,
  Users,
} from "lucide-react";
import { createClient, isSupabaseConfigured } from "@/lib/supabase/client";
import { backend } from "@/lib/backend";
import { indianNumber } from "@/lib/format";
import { SUPPLY_TYPES, SUPPLY_TONE, supplyLabel, type SupplyTypeValue } from "@/lib/supply";
import { ImportPanel } from "@/components/ImportPanel";
import { compareValues, Pagination, SortHeader, type SortState } from "@/components/DataTable";
import { isMissingSchema, MigrationNotice, RlsNotice, SetupNotice } from "@/components/SetupNotice";
import { EmptyState, PageHeader, Tag, TableSkeleton, useToast } from "@/components/ui";
import type { SupplyType } from "@/lib/types";

interface SpaceRow {
  area_sqft: number | null;
  seats: number | null;
  occupancy: string;
  operator_id: string | null;
}

interface Row {
  id: string;
  name: string;
  address: string | null;
  supply_type: SupplyType;
  operator_brand: string | null;
  total_size_sqft: number | null;
  is_verified: boolean;
  micro_markets: { code: string } | null;
  developer: { name: string } | null;
  operator: { id: string; name: string } | null;
  spaces: SpaceRow[];
  building_images: { id: string }[];
}

async function loadBuildings(): Promise<Row[]> {
  const supabase = createClient();
  const { data, error } = await supabase
    .from("buildings")
    .select(
      "id, name, address, supply_type, operator_brand, total_size_sqft, is_verified, " +
        "micro_markets(code), " +
        "developer:organisations!buildings_developer_id_fkey(name), " +
        "operator:organisations!buildings_operator_id_fkey(id, name), " +
        "spaces(area_sqft, seats, occupancy, operator_id), building_images(id)",
    )
    .order("name")
    .limit(5000);
  if (error) throw new Error(error.message);
  return (data ?? []) as unknown as Row[];
}

async function loadOperators(): Promise<{ id: string; name: string }[]> {
  const supabase = createClient();
  const { data } = await supabase
    .from("organisations")
    .select("id, name")
    .in("role", ["operator", "both"])
    .order("name")
    .limit(500);
  return data ?? [];
}

/** Everything the table needs, computed once per building. */
function derive(building: Row) {
  const vacant = building.spaces.filter((s) => s.occupancy === "available");
  const operatorIds = new Set(
    building.spaces.map((s) => s.operator_id).filter(Boolean) as string[],
  );
  if (building.operator?.id) operatorIds.add(building.operator.id);
  return {
    availableSqft: vacant.reduce((sum, s) => sum + Number(s.area_sqft ?? 0), 0),
    availableSeats: vacant.reduce((sum, s) => sum + Number(s.seats ?? 0), 0),
    options: building.spaces.length,
    vacantOptions: vacant.length,
    operatorIds,
    photos: building.building_images.length,
  };
}

export default function DataPage() {
  const toast = useToast();
  const configured = isSupabaseConfigured();

  const { data, error, isLoading, mutate } = useSWR<Row[]>(
    configured ? "buildings-list" : null,
    loadBuildings,
  );
  const { data: operators } = useSWR(configured ? "operators" : null, loadOperators);
  const { data: health } = useSWR("backend-health", () => backend.health(), {
    shouldRetryOnError: false,
  });
  // The backend reads past RLS; a mismatch means policies, not an empty table.
  const backendRows = health?.row_counts?.buildings ?? 0;

  const [search, setSearch] = useState("");
  const [market, setMarket] = useState("");
  const [category, setCategory] = useState("");
  const [operator, setOperator] = useState("");
  const [availability, setAvailability] = useState("");
  const [extras, setExtras] = useState({ photos: false, verified: false });
  const [sort, setSort] = useState<SortState>({ key: "name", direction: "asc" });
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(50);

  const [showImport, setShowImport] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [working, setWorking] = useState(false);

  const markets = useMemo(
    () => [...new Set((data ?? []).map((b) => b.micro_markets?.code).filter(Boolean))].sort(),
    [data],
  );

  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const b of data ?? []) map.set(b.supply_type, (map.get(b.supply_type) ?? 0) + 1);
    return map;
  }, [data]);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = (data ?? []).filter((b) => {
      const d = derive(b);
      if (category && b.supply_type !== category) return false;
      if (market && b.micro_markets?.code !== market) return false;
      if (operator && !d.operatorIds.has(operator)) return false;
      if (availability === "available" && d.vacantOptions === 0) return false;
      if (availability === "none" && d.vacantOptions > 0) return false;
      if (extras.photos && d.photos === 0) return false;
      if (extras.verified && !b.is_verified) return false;
      if (!needle) return true;
      const haystack = `${b.name} ${b.developer?.name ?? ""} ${b.operator?.name ?? ""} ${
        b.operator_brand ?? ""
      } ${b.address ?? ""}`.toLowerCase();
      return haystack.includes(needle);
    });

    return filtered.sort((a, b) => {
      const da = derive(a);
      const db_ = derive(b);
      const pick = (row: Row, d: ReturnType<typeof derive>) =>
        ({
          name: row.name,
          operator: row.operator?.name ?? row.developer?.name ?? "",
          market: row.micro_markets?.code ?? "",
          category: row.supply_type,
          total: row.total_size_sqft,
          available: d.availableSqft || d.availableSeats,
          options: d.options,
          photos: d.photos,
        }) as Record<string, unknown>;
      return compareValues(pick(a, da)[sort.key], pick(b, db_)[sort.key], sort.direction);
    });
  }, [data, search, market, category, operator, availability, extras, sort]);

  // Any filter change should return to the first page, or the view looks empty.
  useEffect(() => setPage(0), [search, market, category, operator, availability, extras, pageSize]);

  const paged = rows.slice(page * pageSize, (page + 1) * pageSize);
  const filtersOn =
    Boolean(search || market || category || operator || availability || extras.photos || extras.verified);
  const allShownSelected = paged.length > 0 && paged.every((r) => selected.has(r.id));

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function clearFilters() {
    setSearch("");
    setMarket("");
    setCategory("");
    setOperator("");
    setAvailability("");
    setExtras({ photos: false, verified: false });
  }

  function onSort(key: string) {
    setSort((prev) =>
      prev.key === key
        ? { key, direction: prev.direction === "asc" ? "desc" : "asc" }
        : { key, direction: "asc" },
    );
  }

  async function recategorise(next: SupplyTypeValue) {
    if (selected.size === 0) return;
    setWorking(true);
    try {
      const supabase = createClient();
      const ids = [...selected];
      const { error: updateError } = await supabase
        .from("buildings")
        .update({ supply_type: next })
        .in("id", ids);
      if (updateError) throw new Error(updateError.message);
      toast({
        tone: "success",
        message: `${ids.length} building${ids.length === 1 ? "" : "s"} moved to ${supplyLabel(next)}.`,
      });
      setSelected(new Set());
      mutate();
    } catch (err) {
      toast({
        tone: "danger",
        title: "Could not re-categorise",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setWorking(false);
    }
  }

  async function markVerified(value: boolean) {
    if (selected.size === 0) return;
    setWorking(true);
    try {
      const supabase = createClient();
      const ids = [...selected];
      await supabase.from("buildings").update({ is_verified: value }).in("id", ids);
      toast({ tone: "success", message: `${ids.length} building(s) marked ${value ? "verified" : "unverified"}.` });
      setSelected(new Set());
      mutate();
    } finally {
      setWorking(false);
    }
  }

  async function deleteSelected() {
    if (selected.size === 0) return;
    const ids = [...selected];
    if (
      !window.confirm(
        `Delete ${ids.length} building${ids.length === 1 ? "" : "s"}? Their spaces, images and contacts go too. This cannot be undone.`,
      )
    ) {
      return;
    }
    setWorking(true);
    try {
      const supabase = createClient();
      const { error: deleteError } = await supabase.from("buildings").delete().in("id", ids);
      if (deleteError) throw new Error(deleteError.message);
      toast({ tone: "success", message: `${ids.length} building(s) deleted.` });
      setSelected(new Set());
      mutate();
    } catch (err) {
      toast({
        tone: "danger",
        title: "Could not delete",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setWorking(false);
    }
  }

  if (!configured) {
    return (
      <>
        <PageHeader eyebrow="Feature 2" title="Supply Database" />
        <SetupNotice />
      </>
    );
  }

  return (
    <>
      <PageHeader
        eyebrow="Feature 2"
        title="Supply Database"
        description="Every building the three tools share — conventional, managed and co-working in one place."
        actions={
          <>
            <Link href="/data/organisations" className="btn-secondary">
              <Users className="h-4 w-4" aria-hidden />
              Duplicate landlords
            </Link>
            <button className="btn-secondary" onClick={() => setShowImport((v) => !v)}>
              <FileSpreadsheet className="h-4 w-4" aria-hidden />
              Import workbook
            </button>
            <Link href="/data/new" className="btn-primary">
              <Plus className="h-4 w-4" aria-hidden />
              New building
            </Link>
          </>
        }
      />

      {showImport ? (
        <div className="mb-6">
          <ImportPanel onClose={() => setShowImport(false)} onDone={() => mutate()} />
        </div>
      ) : null}

      {/* ------------------------------------------------------ category tabs */}
      <div className="mb-4 flex flex-wrap items-center gap-1 border-b border-border">
        {[
          { value: "", label: "All", count: data?.length ?? 0 },
          ...SUPPLY_TYPES.map((t) => ({
            value: t.value as string,
            label: t.label,
            count: counts.get(t.value) ?? 0,
          })),
        ]
          .filter(
            (tab) =>
              tab.value === "" ||
              tab.count > 0 ||
              ["conventional", "managed", "coworking"].includes(tab.value),
          )
          .map((tab) => {
            const active = category === tab.value;
            return (
              <button
                key={tab.value || "all"}
                onClick={() => setCategory(tab.value)}
                aria-pressed={active}
                className={`-mb-px border-b-2 px-3.5 py-2.5 text-sm transition-colors ${
                  active
                    ? "border-accent font-medium text-accent"
                    : "border-transparent text-ink-2 hover:text-ink"
                }`}
              >
                {tab.label}
                <span
                  className={`ml-1.5 text-xs tabular-nums ${active ? "text-accent/70" : "text-ink-3"}`}
                >
                  {indianNumber(tab.count)}
                </span>
              </button>
            );
          })}
      </div>

      {/* ---------------------------------------------------------- filters */}
      <div className="mb-3 flex flex-wrap gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search
            className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-ink-3"
            aria-hidden
          />
          <input
            className="field pl-9"
            placeholder="Search building, operator, landlord or address"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search buildings"
          />
        </div>
        <select
          className="field w-auto"
          value={market}
          onChange={(e) => setMarket(e.target.value)}
          aria-label="Micro-market"
        >
          <option value="">All micro-markets</option>
          {markets.map((code) => (
            <option key={code} value={code!}>
              {code}
            </option>
          ))}
        </select>
        <select
          className="field w-auto max-w-[220px]"
          value={operator}
          onChange={(e) => setOperator(e.target.value)}
          aria-label="Operator"
        >
          <option value="">All operators</option>
          {(operators ?? []).map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
        <select
          className="field w-auto"
          value={availability}
          onChange={(e) => setAvailability(e.target.value)}
          aria-label="Availability"
        >
          <option value="">Any availability</option>
          <option value="available">Has vacancy</option>
          <option value="none">Fully occupied</option>
        </select>
        {filtersOn ? (
          <button className="btn-ghost" onClick={clearFilters}>
            Clear
          </button>
        ) : null}
      </div>

      <div className="mb-4 flex flex-wrap gap-4 text-sm">
        <label className="flex cursor-pointer items-center gap-2 text-ink-2">
          <input
            type="checkbox"
            checked={extras.photos}
            onChange={(e) => setExtras((p) => ({ ...p, photos: e.target.checked }))}
          />
          Has photographs
        </label>
        <label className="flex cursor-pointer items-center gap-2 text-ink-2">
          <input
            type="checkbox"
            checked={extras.verified}
            onChange={(e) => setExtras((p) => ({ ...p, verified: e.target.checked }))}
          />
          Checked by a human
        </label>
      </div>

      {/* ------------------------------------------------------ bulk actions */}
      {selected.size > 0 ? (
        <div className="animate-in card sticky top-16 z-10 mb-3 flex flex-wrap items-center gap-2 p-3">
          <span className="text-sm font-medium">{selected.size} selected</span>
          <span className="ml-2 text-sm text-ink-2">Move to</span>
          {SUPPLY_TYPES.filter((t) => t.importable).map((type) => (
            <button
              key={type.value}
              className="btn-secondary btn-sm"
              disabled={working}
              onClick={() => recategorise(type.value)}
            >
              {type.label}
            </button>
          ))}
          <span className="mx-1 h-4 w-px bg-border" />
          <button className="btn-secondary btn-sm" disabled={working} onClick={() => markVerified(true)}>
            Mark verified
          </button>
          <span className="flex-1" />
          <button className="btn-danger btn-sm" disabled={working} onClick={deleteSelected}>
            <Trash2 className="h-3.5 w-3.5" aria-hidden />
            Delete
          </button>
          <button className="btn-ghost btn-sm" onClick={() => setSelected(new Set())}>
            Cancel
          </button>
        </div>
      ) : null}

      {isLoading ? (
        <TableSkeleton />
      ) : error ? (
        isMissingSchema(error) ? (
          <MigrationNotice />
        ) : (
          <EmptyState icon={Building2} title="Could not load buildings">
            {(error as Error).message}
          </EmptyState>
        )
      ) : (data?.length ?? 0) === 0 && backendRows > 0 ? (
        <RlsNotice backendRows={backendRows} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Building2}
          title={filtersOn ? "No buildings match those filters" : "No buildings yet"}
          action={
            filtersOn ? (
              <button className="btn-secondary" onClick={clearFilters}>
                Clear filters
              </button>
            ) : (
              <button className="btn-primary" onClick={() => setShowImport(true)}>
                Import a workbook
              </button>
            )
          }
        >
          {filtersOn
            ? "Try a broader search."
            : "Import a supply workbook, or run the extraction pipeline, to fill the database."}
        </EmptyState>
      ) : (
        <>
          <div className="card table-scroll overflow-hidden">
            <table className="w-full min-w-[1040px]">
              <thead className="bg-surface-2">
                <tr>
                  <th className="th w-10">
                    <input
                      type="checkbox"
                      aria-label="Select all shown"
                      checked={allShownSelected}
                      onChange={(e) =>
                        setSelected((prev) => {
                          const next = new Set(prev);
                          paged.forEach((r) => (e.target.checked ? next.add(r.id) : next.delete(r.id)));
                          return next;
                        })
                      }
                    />
                  </th>
                  <SortHeader label="Building" columnKey="name" sort={sort} onSort={onSort} />
                  <SortHeader label="Operator / Landlord" columnKey="operator" sort={sort} onSort={onSort} />
                  <SortHeader label="Market" columnKey="market" sort={sort} onSort={onSort} />
                  <SortHeader label="Category" columnKey="category" sort={sort} onSort={onSort} />
                  <SortHeader label="Options" columnKey="options" sort={sort} onSort={onSort} align="right" />
                  <SortHeader label="Total" columnKey="total" sort={sort} onSort={onSort} align="right" />
                  <SortHeader label="Available" columnKey="available" sort={sort} onSort={onSort} align="right" />
                  <SortHeader label="Photos" columnKey="photos" sort={sort} onSort={onSort} align="right" />
                  <th className="th w-10" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {paged.map((building) => {
                  const d = derive(building);
                  const isSelected = selected.has(building.id);
                  const multiOperator = d.operatorIds.size > 1;
                  return (
                    <tr
                      key={building.id}
                      className={`row-hover group ${isSelected ? "bg-accent-soft/50" : ""}`}
                    >
                      <td className="td">
                        <input
                          type="checkbox"
                          aria-label={`Select ${building.name}`}
                          checked={isSelected}
                          onChange={() => toggle(building.id)}
                        />
                      </td>
                      <td className="td">
                        <Link href={`/data/${building.id}`} className="font-medium hover:text-accent">
                          {building.name}
                        </Link>
                        {building.address ? (
                          <div className="mt-0.5 max-w-[30ch] truncate text-xs text-ink-3">
                            {building.address}
                          </div>
                        ) : null}
                      </td>
                      <td className="td text-ink-2">
                        {multiOperator ? (
                          <span className="chip bg-surface-2 text-ink-2">
                            {d.operatorIds.size} operators
                          </span>
                        ) : (
                          (building.operator?.name ?? building.developer?.name ?? "—")
                        )}
                        {building.operator_brand ? (
                          <div className="mt-0.5 text-xs text-ink-3">{building.operator_brand}</div>
                        ) : null}
                      </td>
                      <td className="td">
                        {building.micro_markets?.code ? (
                          <Tag>{building.micro_markets.code}</Tag>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="td">
                        <span className={`chip ${SUPPLY_TONE[building.supply_type] ?? ""}`}>
                          {supplyLabel(building.supply_type)}
                        </span>
                      </td>
                      <td className="td text-right tabular-nums">
                        {d.options || "—"}
                        {d.vacantOptions > 0 && d.vacantOptions !== d.options ? (
                          <span className="text-ink-3"> ({d.vacantOptions} free)</span>
                        ) : null}
                      </td>
                      <td className="td text-right tabular-nums">
                        {building.total_size_sqft ? indianNumber(building.total_size_sqft) : "—"}
                      </td>
                      <td className="td text-right font-medium tabular-nums">
                        {d.availableSqft > 0
                          ? indianNumber(d.availableSqft)
                          : d.availableSeats > 0
                            ? `${indianNumber(d.availableSeats)} seats`
                            : "—"}
                      </td>
                      <td className="td text-right tabular-nums text-ink-3">
                        {d.photos ? (
                          <span className="inline-flex items-center gap-1">
                            <Images className="h-3.5 w-3.5" aria-hidden />
                            {d.photos}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="td">
                        <Link
                          href={`/data/${building.id}`}
                          aria-label={`Open ${building.name}`}
                          className="grid h-7 w-7 place-items-center rounded-md text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-surface-3 hover:text-ink"
                        >
                          <ChevronRight className="h-4 w-4" aria-hidden />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pagination
            page={page}
            pageSize={pageSize}
            total={rows.length}
            onPage={setPage}
            onPageSize={setPageSize}
          />
        </>
      )}
    </>
  );
}
