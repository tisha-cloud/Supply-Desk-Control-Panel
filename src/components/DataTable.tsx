"use client";

import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";

export type SortDirection = "asc" | "desc";

export interface SortState {
  key: string;
  direction: SortDirection;
}

/** A sortable column header. Clicking cycles ascending -> descending. */
export function SortHeader({
  label,
  columnKey,
  sort,
  onSort,
  align = "left",
  className = "",
}: {
  label: string;
  columnKey: string;
  sort: SortState;
  onSort: (key: string) => void;
  align?: "left" | "right";
  className?: string;
}) {
  const active = sort.key === columnKey;
  const Icon = !active ? ChevronsUpDown : sort.direction === "asc" ? ArrowUp : ArrowDown;
  return (
    <th className={`th ${className}`} aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}>
      <button
        type="button"
        onClick={() => onSort(columnKey)}
        className={`flex w-full items-center gap-1 transition-colors hover:text-ink ${
          align === "right" ? "justify-end" : ""
        } ${active ? "text-ink" : ""}`}
      >
        {label}
        <Icon className={`h-3 w-3 ${active ? "opacity-100" : "opacity-40"}`} aria-hidden />
      </button>
    </th>
  );
}

/** Compare helper that keeps blanks at the bottom regardless of direction. */
export function compareValues(a: unknown, b: unknown, direction: SortDirection): number {
  const blankA = a === null || a === undefined || a === "";
  const blankB = b === null || b === undefined || b === "";
  if (blankA && blankB) return 0;
  if (blankA) return 1;
  if (blankB) return -1;

  let result: number;
  if (typeof a === "number" && typeof b === "number") result = a - b;
  else result = String(a).localeCompare(String(b), undefined, { numeric: true });
  return direction === "asc" ? result : -result;
}

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
  onPageSize,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
  onPageSize: (size: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);

  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm">
      <span className="text-ink-3 tabular-nums">
        {from}–{to} of {total.toLocaleString()}
      </span>
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1.5 text-ink-3">
          Rows
          <select
            className="field field-sm w-auto"
            value={pageSize}
            onChange={(e) => {
              onPageSize(Number(e.target.value));
              onPage(0);
            }}
            aria-label="Rows per page"
          >
            {[25, 50, 100, 250].map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
        <button className="btn-secondary btn-sm" onClick={() => onPage(page - 1)} disabled={page === 0}>
          Previous
        </button>
        <span className="text-ink-3 tabular-nums">
          {page + 1} / {pages}
        </span>
        <button
          className="btn-secondary btn-sm"
          onClick={() => onPage(page + 1)}
          disabled={page + 1 >= pages}
        >
          Next
        </button>
      </div>
    </div>
  );
}
