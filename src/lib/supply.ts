/**
 * The supply categories the desk trades.
 *
 * Managed and coworking come from the same operators but are different
 * products: a managed suite is private and built out, coworking is shared or
 * hot-desk inventory. They are separate categories rather than a flag so a
 * single operator can supply both without the records fighting each other.
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
    label: "Managed",
    hint: "Private built-out suites, let by seat or floor",
    importable: true,
    tone: "bg-positive-soft text-positive",
  },
  {
    value: "coworking",
    label: "Co-working",
    hint: "Shared and hot-desk inventory",
    importable: true,
    tone: "bg-warning-soft text-warning",
  },
  { value: "sale", label: "Sale", hint: "Strata / outright purchase", importable: false, tone: "bg-surface-2 text-ink-2" },
  { value: "other", label: "Other", hint: "Retail, industrial, out of scope", importable: false, tone: "bg-surface-2 text-ink-3" },
] as const;

export type SupplyTypeValue = (typeof SUPPLY_TYPES)[number]["value"];

export const SUPPLY_LABEL: Record<string, string> = Object.fromEntries(
  SUPPLY_TYPES.map((t) => [t.value, t.label]),
);

export const SUPPLY_TONE: Record<string, string> = Object.fromEntries(
  SUPPLY_TYPES.map((t) => [t.value, t.tone]),
);

export function supplyLabel(value: string | null | undefined): string {
  return SUPPLY_LABEL[value ?? ""] ?? value ?? "—";
}
