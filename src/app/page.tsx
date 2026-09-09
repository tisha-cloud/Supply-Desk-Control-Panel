"use client";

import Link from "next/link";
import useSWR from "swr";
import {
  ArrowRight,
  Building2,
  Database,
  FileSearch,
  Images,
  Presentation,
} from "lucide-react";
import { createClient, isSupabaseConfigured } from "@/lib/supabase/client";
import { backend } from "@/lib/backend";
import { indianNumber } from "@/lib/format";
import { supplyLabel } from "@/lib/supply";
import { BarList, SplitBar } from "@/components/charts";
import { isMissingSchema, MigrationNotice, RlsNotice, SetupNotice } from "@/components/SetupNotice";
import {
  Callout,
  EmptyState,
  PageHeader,
  Section,
  Stat,
  StatSkeleton,
} from "@/components/ui";

interface Totals {
  buildings: number;
  conventional: number;
  managed: number;
  spaces: number;
  availableSqft: number;
  occupiedSqft: number;
  availableSeats: number;
  images: number;
  landlords: number;
  verified: number;
  microMarkets: { label: string; value: number; secondary: string }[];
  categories: { label: string; value: number; secondary: string }[];
}

async function loadTotals(): Promise<Totals> {
  const supabase = createClient();

  const [buildings, spaces, images, organisations, markets] = await Promise.all([
    supabase.from("buildings").select("id, supply_type, micro_market_id, is_verified"),
    supabase.from("spaces").select("building_id, area_sqft, seats, occupancy"),
    supabase.from("building_images").select("id", { count: "exact", head: true }),
    supabase.from("organisations").select("id", { count: "exact", head: true }),
    supabase.from("micro_markets").select("id, code"),
  ]);

  if (buildings.error) throw new Error(buildings.error.message);

  const buildingRows = buildings.data ?? [];
  const spaceRows = spaces.data ?? [];
  const marketById = new Map((markets.data ?? []).map((m) => [m.id, m.code]));

  const stats = new Map<string, { buildings: number; available: number }>();
  for (const building of buildingRows) {
    const code = marketById.get(building.micro_market_id ?? "") ?? "Unassigned";
    const entry = stats.get(code) ?? { buildings: 0, available: 0 };
    entry.buildings += 1;
    stats.set(code, entry);
  }

  const marketOf = new Map(
    buildingRows.map((b) => [b.id, marketById.get(b.micro_market_id ?? "") ?? "Unassigned"]),
  );

  let availableSqft = 0;
  let occupiedSqft = 0;
  let availableSeats = 0;
  for (const space of spaceRows) {
    const area = Number(space.area_sqft ?? 0);
    if (space.occupancy === "available") {
      availableSqft += area;
      availableSeats += Number(space.seats ?? 0);
      const code = marketOf.get(space.building_id) ?? "Unassigned";
      const entry = stats.get(code) ?? { buildings: 0, available: 0 };
      entry.available += area;
      stats.set(code, entry);
    } else if (space.occupancy === "occupied") {
      occupiedSqft += area;
    }
  }

  // Available area per category, so the three products can be compared directly.
  const byCategory = new Map<string, { buildings: number; available: number }>();
  for (const building of buildingRows) {
    const entry = byCategory.get(building.supply_type) ?? { buildings: 0, available: 0 };
    entry.buildings += 1;
    byCategory.set(building.supply_type, entry);
  }
  const categoryOf = new Map(buildingRows.map((b) => [b.id, b.supply_type]));
  for (const space of spaceRows) {
    if (space.occupancy !== "available") continue;
    const key = categoryOf.get(space.building_id);
    if (!key) continue;
    const entry = byCategory.get(key) ?? { buildings: 0, available: 0 };
    entry.available += Number(space.area_sqft ?? 0);
    byCategory.set(key, entry);
  }

  return {
    buildings: buildingRows.length,
    conventional: buildingRows.filter((b) => b.supply_type === "conventional").length,
    managed: buildingRows.filter((b) => b.supply_type === "managed").length,
    spaces: spaceRows.length,
    availableSqft,
    occupiedSqft,
    availableSeats,
    images: images.count ?? 0,
    landlords: organisations.count ?? 0,
    verified: buildingRows.filter((b) => b.is_verified).length,
    microMarkets: [...stats.entries()]
      .map(([code, v]) => ({
        label: code,
        value: v.available,
        secondary: `${v.buildings} building${v.buildings === 1 ? "" : "s"}`,
      }))
      .filter((m) => m.value > 0)
      .sort((a, b) => b.value - a.value),
    categories: [...byCategory.entries()]
      .map(([key, v]) => ({
        label: supplyLabel(key),
        value: v.buildings,
        secondary: v.available > 0 ? `${indianNumber(v.available)} Sft available` : "seats only",
      }))
      .sort((a, b) => b.value - a.value),
  };
}

const FEATURES = [
  {
    href: "/extraction",
    icon: FileSearch,
    title: "Extraction",
    body: "Read landlord PDFs, decks, spreadsheets and screenshots into the database — with occupied space derived from what each document leaves out.",
  },
  {
    href: "/data",
    icon: Database,
    title: "Supply Database",
    body: "Import the Managed Office workbook with its photographs, then correct buildings, availability and contacts by hand.",
  },
  {
    href: "/decks",
    icon: Presentation,
    title: "Deck Builder",
    body: "Describe a requirement in plain English and get a client-ready options deck built from live records.",
  },
];

export default function OverviewPage() {
  const configured = isSupabaseConfigured();
  const { data, error, isLoading } = useSWR<Totals>(
    configured ? "overview-totals" : null,
    loadTotals,
  );
  const { data: health } = useSWR("backend-health", () => backend.health(), {
    shouldRetryOnError: false,
  });
  // The backend reads past RLS; if it sees rows and we do not, say so plainly.
  const backendRows = health?.row_counts?.buildings ?? 0;
  const blockedByRls = Boolean(data && data.buildings === 0 && backendRows > 0);

  const hasData = Boolean(data && data.buildings > 0);

  return (
    <>
      <PageHeader
        eyebrow="Bengaluru commercial supply"
        title="Overview"
        description="One database behind three tools: document extraction, the supply record itself, and client deck generation."
      />

      {!configured ? (
        <div className="mb-6">
          <SetupNotice />
        </div>
      ) : null}

      {configured ? (
        <>
          {isLoading ? (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 4 }).map((_, index) => (
                <StatSkeleton key={index} />
              ))}
            </div>
          ) : error ? (
            isMissingSchema(error) ? (
              <MigrationNotice />
            ) : (
              <Callout tone="danger" title="Could not read the database">
                {(error as Error).message}
              </Callout>
            )
          ) : blockedByRls ? (
            <RlsNotice backendRows={backendRows} />
          ) : !hasData ? (
            <EmptyState
              icon={Building2}
              title="The database is empty"
              action={
                <div className="flex flex-wrap justify-center gap-2">
                  <Link href="/data" className="btn-primary">
                    Import the workbook
                  </Link>
                  <Link href="/extraction" className="btn-secondary">
                    Run extraction
                  </Link>
                </div>
              }
            >
              Import the Managed Office workbook, or run the extraction pipeline over your
              landlord documents, to fill it.
            </EmptyState>
          ) : data ? (
            <>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <Stat
                  emphasis
                  label="Available space"
                  value={
                    <>
                      {indianNumber(data.availableSqft)}
                      <span className="ml-1.5 text-base font-normal text-ink-3">Sft</span>
                    </>
                  }
                  hint={
                    data.availableSeats > 0
                      ? `plus ${indianNumber(data.availableSeats)} managed seats`
                      : `across ${indianNumber(data.spaces)} space records`
                  }
                />
                <Stat
                  label="Buildings"
                  value={indianNumber(data.buildings)}
                  hint={`${data.conventional} conventional · ${data.managed} managed`}
                />
                <Stat
                  label="Occupied"
                  value={
                    <>
                      {indianNumber(data.occupiedSqft)}
                      <span className="ml-1.5 text-base font-normal text-ink-3">Sft</span>
                    </>
                  }
                  hint="includes derived balance rows"
                />
                <Stat
                  label="Photographs"
                  value={indianNumber(data.images)}
                  hint={`${data.landlords} landlords and operators`}
                  trend={<Images className="h-5 w-5 text-ink-3" aria-hidden />}
                />
              </div>

              <div className="mt-6 grid gap-5 lg:grid-cols-[1.4fr_1fr]">
                <Section
                  title="Available space by micro-market"
                  description="Vacant area currently on offer, largest first."
                >
                  <BarList data={data.microMarkets} unit="Sft" />
                </Section>

                <div className="space-y-5">
                  <Section
                    title="Portfolio split"
                    description="How much of the recorded stock is on the market."
                  >
                    <SplitBar
                      primaryLabel="Available"
                      primaryValue={data.availableSqft}
                      restLabel="Occupied"
                      restValue={data.occupiedSqft}
                    />
                  </Section>

                  <Section
                    title="Supply categories"
                    description="Buildings recorded in each of the three products."
                  >
                    <BarList data={data.categories} unit="" emptyLabel="Nothing categorised yet" />
                  </Section>

                  <Section title="Data quality">
                    <dl className="space-y-3 text-sm">
                      <div className="flex items-baseline justify-between gap-4">
                        <dt className="text-ink-2">Checked by a human</dt>
                        <dd className="font-medium tabular-nums">
                          {indianNumber(data.verified)}
                          <span className="text-ink-3"> / {indianNumber(data.buildings)}</span>
                        </dd>
                      </div>
                      <div className="flex items-baseline justify-between gap-4">
                        <dt className="text-ink-2">Space records</dt>
                        <dd className="font-medium tabular-nums">{indianNumber(data.spaces)}</dd>
                      </div>
                      <div className="flex items-baseline justify-between gap-4">
                        <dt className="text-ink-2">Micro-markets covered</dt>
                        <dd className="font-medium tabular-nums">{data.microMarkets.length}</dd>
                      </div>
                    </dl>
                    <Link href="/data" className="btn-secondary btn-sm mt-4 w-full">
                      Open supply database
                    </Link>
                  </Section>
                </div>
              </div>
            </>
          ) : null}
        </>
      ) : null}

      <section className="mt-8 grid gap-4 md:grid-cols-3">
        {FEATURES.map(({ href, icon: Icon, title, body }) => (
          <Link key={href} href={href} className="card card-lift group p-5">
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-accent-soft text-accent">
              <Icon className="h-4.5 w-4.5" aria-hidden />
            </span>
            <div className="mt-3.5 flex items-center gap-1.5 font-semibold">
              {title}
              <ArrowRight
                className="h-4 w-4 -translate-x-1 opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-100"
                aria-hidden
              />
            </div>
            <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{body}</p>
          </Link>
        ))}
      </section>
    </>
  );
}
