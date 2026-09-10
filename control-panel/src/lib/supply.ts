/**
 * The three categories the desk trades, and the rule that separates a managed
 * requirement from a co-working one.
 *
 * Managed and co-working are deliberately ONE listing category. The listing is
 * identical - the same operator, the same centre, the same seats - and only the
 * size of the requirement decides what the client is buying:
 *
 *     fewer than 15 seats  ->  co-working
 *     15 seats or more     ->  managed
 *
 * So the product name belongs to the requirement, not to the record. It is
 * applied in the deck builder, where the requirement is known.
 */
export const SUPPLY_TYPES = [
  {
    value: "conventional",
    label: "Conventional",
    hint: "Let by the floor, direct from the landlord",
    importable: true,
    tone: "bg-accent-soft text-accent",
  },
  {
    value: "managed",
    label: "Managed / Co-working",
    hint: "Operator-run centres, let by seat or suite",
    importable: true,
    tone: "bg-positive-soft text-positive",
  },
  {
    value: "sale",
    label: "Sale",
    hint: "Strata or outright purchase",
    importable: true,
    tone: "bg-warning-soft text-warning",
  },
] as const;

export type SupplyTypeValue = (typeof SUPPLY_TYPES)[number]["value"];

/**
 * Values written before managed and co-working were merged. They are folded
 * into a live category on read so a record restored from an old backup still
 * lands in the right tab; nothing writes them.
 */
const LEGACY: Record<string, SupplyTypeValue> = {
  coworking: "managed",
  "co-working": "managed",
  flex: "managed",
};

/** The listing category a stored value belongs to. */
export function canonicalSupplyType(value: string | null | undefined): string {
  const text = (value ?? "").trim().toLowerCase();
  return LEGACY[text] ?? text;
}

export const SUPPLY_LABEL: Record<string, string> = Object.fromEntries(
  SUPPLY_TYPES.map((t) => [t.value, t.label]),
);

export const SUPPLY_TONE: Record<string, string> = Object.fromEntries(
  SUPPLY_TYPES.map((t) => [t.value, t.tone]),
);

export function supplyLabel(value: string | null | undefined): string {
  const canonical = canonicalSupplyType(value);
  return SUPPLY_LABEL[canonical] ?? (value || "—");
}

export function supplyTone(value: string | null | undefined): string {
  return SUPPLY_TONE[canonicalSupplyType(value)] ?? "bg-surface-2 text-ink-3";
}

/** Below this a requirement is co-working; at or above it, managed. */
export const MANAGED_SEAT_THRESHOLD = 15;

/** Which product a requirement for this many seats is asking for. */
export function productForSeats(seats: number | null | undefined): "coworking" | "managed" | null {
  if (seats == null || !Number.isFinite(seats) || seats <= 0) return null;
  return seats < MANAGED_SEAT_THRESHOLD ? "coworking" : "managed";
}

export const PRODUCT_LABEL: Record<string, string> = {
  coworking: "Co-working",
  managed: "Managed Office",
  conventional: "Conventional",
  sale: "Sale",
};
