"use client";

/**
 * Charts for this app, built to fixed mark specs:
 *   - one series -> one colour (never a value ramp across nominal categories)
 *   - bars capped at 24px with a 4px rounded data-end, square at the baseline
 *   - hairline recessive gridlines, never dashed
 *   - a 2px surface gap separating touching segments
 *   - values direct-labelled at the tip; text always in ink tokens, never the
 *     series colour
 *   - hover tooltips, because an HTML chart is interactive by default
 */
import { useState } from "react";
import { indianNumber } from "@/lib/format";

export interface BarDatum {
  label: string;
  value: number;
  secondary?: string;
}

/**
 * Horizontal bars for magnitude across nominal categories (micro-markets).
 * Horizontal because the category labels are words, not dates.
 */
export function BarList({
  data,
  unit = "Sft",
  max: providedMax,
  emptyLabel = "No data yet",
}: {
  data: BarDatum[];
  unit?: string;
  max?: number;
  emptyLabel?: string;
}) {
  const [hovered, setHovered] = useState<string | null>(null);

  if (data.length === 0) {
    return <p className="py-8 text-center text-sm text-ink-3">{emptyLabel}</p>;
  }

  const max = providedMax ?? Math.max(...data.map((d) => d.value), 1);

  return (
    <ul className="space-y-1">
      {data.map((datum) => {
        const pct = max > 0 ? Math.max((datum.value / max) * 100, datum.value > 0 ? 1.5 : 0) : 0;
        const active = hovered === datum.label;
        return (
          <li
            key={datum.label}
            className="group relative grid grid-cols-[minmax(88px,132px)_1fr_auto] items-center gap-3 rounded-lg px-2 py-1.5 transition-colors"
            style={{ background: active ? "var(--surface-2)" : "transparent" }}
            onMouseEnter={() => setHovered(datum.label)}
            onMouseLeave={() => setHovered(null)}
          >
            <span className="truncate text-sm text-ink-2" title={datum.label}>
              {datum.label}
            </span>

            <span className="relative block h-4">
              {/* track keeps the row height stable when a value is zero */}
              <span
                className="absolute inset-y-0 left-0 block rounded-r-[4px]"
                style={{
                  width: `${pct}%`,
                  height: "16px",
                  background: "var(--chart-1)",
                  opacity: hovered && !active ? 0.45 : 1,
                  transition: "width 420ms cubic-bezier(0.16,1,0.3,1), opacity 140ms ease",
                }}
              />
            </span>

            <span className="text-right text-sm font-medium tabular-nums text-ink">
              {indianNumber(datum.value)}
              <span className="ml-1 text-xs font-normal text-ink-3">{unit}</span>
            </span>

            {active && datum.secondary ? (
              <span className="pointer-events-none absolute -top-1 right-2 z-10 -translate-y-full rounded-md border border-border bg-surface px-2 py-1 text-xs whitespace-nowrap text-ink-2 shadow-[var(--shadow-md)]">
                {datum.secondary}
              </span>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Part-to-whole for exactly two complementary quantities. Emphasis pattern:
 * the measure that matters carries the series colour, the remainder is grey.
 * A legend is present because there are two segments.
 */
export function SplitBar({
  primaryLabel,
  primaryValue,
  restLabel,
  restValue,
  unit = "Sft",
}: {
  primaryLabel: string;
  primaryValue: number;
  restLabel: string;
  restValue: number;
  unit?: string;
}) {
  const total = primaryValue + restValue;
  const pct = total > 0 ? (primaryValue / total) * 100 : 0;

  return (
    <div>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-surface-2">
        <div
          className="h-full"
          style={{
            width: `${pct}%`,
            background: "var(--chart-1)",
            transition: "width 480ms cubic-bezier(0.16,1,0.3,1)",
          }}
        />
        {/* 2px surface gap does the separating - no stroke around the marks */}
        <div className="h-full shrink-0" style={{ width: 2, background: "var(--surface)" }} />
        <div className="h-full flex-1" style={{ background: "var(--chart-rest)" }} />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm">
        <span className="flex items-center gap-2">
          <span
            className="h-2.5 w-2.5 shrink-0 rounded-full"
            style={{ background: "var(--chart-1)" }}
            aria-hidden
          />
          <span className="text-ink-2">{primaryLabel}</span>
          <span className="font-medium tabular-nums text-ink">
            {indianNumber(primaryValue)}
            <span className="ml-1 text-xs font-normal text-ink-3">{unit}</span>
          </span>
        </span>
        <span className="flex items-center gap-2">
          <span
            className="h-2.5 w-2.5 shrink-0 rounded-full"
            style={{ background: "var(--chart-rest)" }}
            aria-hidden
          />
          <span className="text-ink-2">{restLabel}</span>
          <span className="font-medium tabular-nums text-ink">
            {indianNumber(restValue)}
            <span className="ml-1 text-xs font-normal text-ink-3">{unit}</span>
          </span>
        </span>
      </div>
    </div>
  );
}

/** Twelve-point sparkline for a stat tile. De-emphasised, no axes, no labels. */
export function Sparkline({ points }: { points: number[] }) {
  if (points.length < 2) return null;
  const max = Math.max(...points);
  const min = Math.min(...points);
  const span = max - min || 1;
  const width = 96;
  const height = 24;

  const d = points
    .map((value, index) => {
      const x = (index / (points.length - 1)) * width;
      const y = height - ((value - min) / span) * height;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden focusable="false">
      <path d={d} fill="none" stroke="var(--chart-1)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
