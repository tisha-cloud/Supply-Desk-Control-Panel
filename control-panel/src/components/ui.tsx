"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Info,
  Loader2,
  X,
  XCircle,
} from "lucide-react";
import type { JobStatus } from "@/lib/types";

/* ------------------------------------------------------------------ layout */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-7 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        {eyebrow ? <div className="eyebrow mb-1.5">{eyebrow}</div> : null}
        <h1 className="text-2xl font-semibold tracking-tight text-balance">{title}</h1>
        {description ? (
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-2">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function Section({
  title,
  description,
  actions,
  children,
  className = "",
}: {
  title?: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`card p-5 sm:p-6 ${className}`}>
      {title || actions ? (
        <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {title ? <h2 className="font-semibold tracking-tight">{title}</h2> : null}
            {description ? (
              <p className="mt-1 max-w-xl text-sm text-ink-2">{description}</p>
            ) : null}
          </div>
          {actions ? <div className="flex shrink-0 gap-2">{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}

/* ------------------------------------------------------------------ figures */
/** Stat tile: label · value · optional delta or hint. The number is the chart. */
export function Stat({
  label,
  value,
  hint,
  trend,
  emphasis = false,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  trend?: React.ReactNode;
  emphasis?: boolean;
}) {
  return (
    <div className="card card-lift p-4 sm:p-5">
      <div className="eyebrow">{label}</div>
      <div className="mt-2 flex items-end justify-between gap-3">
        <div
          className={`font-semibold tracking-tight ${emphasis ? "text-3xl sm:text-4xl" : "text-2xl"}`}
        >
          {value}
        </div>
        {trend}
      </div>
      {hint ? <div className="mt-1.5 text-xs text-ink-3">{hint}</div> : null}
    </div>
  );
}

/* ------------------------------------------------------------------ status */
const TONES = {
  info: { cls: "border-accent-border bg-accent-soft text-accent", Icon: Info },
  success: { cls: "border-transparent bg-positive-soft text-positive", Icon: CheckCircle2 },
  warning: { cls: "border-transparent bg-warning-soft text-warning", Icon: AlertTriangle },
  danger: { cls: "border-transparent bg-danger-soft text-danger", Icon: XCircle },
} as const;

export function Callout({
  tone = "info",
  title,
  children,
  onDismiss,
}: {
  tone?: keyof typeof TONES;
  title?: string;
  children: React.ReactNode;
  onDismiss?: () => void;
}) {
  const { cls, Icon } = TONES[tone];
  return (
    <div className={`animate-in flex gap-3 rounded-xl border p-4 text-sm ${cls}`}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        {title ? <div className="mb-1 font-semibold">{title}</div> : null}
        <div className="[&_a]:underline [&_code]:rounded [&_code]:bg-black/10 [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[0.85em]">
          {children}
        </div>
      </div>
      {onDismiss ? (
        <button className="shrink-0 opacity-60 hover:opacity-100" aria-label="Dismiss" onClick={onDismiss}>
          <X className="h-4 w-4" aria-hidden />
        </button>
      ) : null}
    </div>
  );
}

/** Status colours are reserved and always ship with a label, never colour alone. */
export function StatusChip({ status }: { status: JobStatus | string }) {
  const map: Record<string, string> = {
    succeeded: "bg-positive-soft text-positive",
    running: "bg-accent-soft text-accent",
    queued: "bg-surface-2 text-ink-2",
    failed: "bg-danger-soft text-danger",
    cancelled: "bg-surface-2 text-ink-3",
  };
  return (
    <span className={`chip ${map[status] ?? "bg-surface-2 text-ink-2"}`}>
      {status === "running" ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : null}
      {status}
    </span>
  );
}

export function OccupancyChip({ occupancy, derived }: { occupancy: string; derived?: boolean }) {
  const map: Record<string, string> = {
    available: "bg-positive-soft text-positive",
    occupied: "bg-surface-2 text-ink-2",
    unknown: "bg-warning-soft text-warning",
  };
  return (
    <span className={`chip ${map[occupancy] ?? "bg-surface-2 text-ink-2"}`}>
      {occupancy}
      {derived ? (
        <span className="opacity-70" title="Derived, not stated in the source document">
          · est
        </span>
      ) : null}
    </span>
  );
}

export function Tag({ children }: { children: React.ReactNode }) {
  return <span className="chip border border-border bg-surface-2 text-ink-2">{children}</span>;
}

/* ----------------------------------------------------------------- loading */
export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-8 text-sm text-ink-2">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {label ?? "Loading…"}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

export function StatSkeleton() {
  return (
    <div className="card p-5">
      <Skeleton className="h-3 w-20" />
      <Skeleton className="mt-3 h-8 w-28" />
      <Skeleton className="mt-2 h-3 w-32" />
    </div>
  );
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="card divide-y divide-border">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="flex items-center gap-4 p-4">
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-20" />
        </div>
      ))}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="card grid place-items-center px-6 py-14 text-center">
      {Icon ? (
        <span className="mb-3 grid h-11 w-11 place-items-center rounded-full bg-surface-2 text-ink-3">
          <Icon className="h-5 w-5" />
        </span>
      ) : null}
      <div className="font-medium">{title}</div>
      {children ? <p className="mt-1.5 max-w-md text-sm text-ink-2">{children}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ProgressBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div
      className="h-2 w-full overflow-hidden rounded-full bg-surface-2"
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className="h-full rounded-full"
        style={{
          width: `${pct}%`,
          background: "var(--chart-1)",
          transition: "width 500ms cubic-bezier(0.16,1,0.3,1)",
        }}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ toasts */
interface Toast {
  id: number;
  tone: keyof typeof TONES;
  title?: string;
  message: string;
}

const ToastContext = createContext<(toast: Omit<Toast, "id">) => void>(() => {});

export function useToast() {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((toast: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { ...toast, id }]);
    setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), 6000);
  }, []);

  const value = useMemo(() => push, [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2"
        aria-live="polite"
      >
        {toasts.map((toast) => (
          <div key={toast.id} className="pointer-events-auto">
            <Callout
              tone={toast.tone}
              title={toast.title}
              onDismiss={() => setToasts((current) => current.filter((t) => t.id !== toast.id))}
            >
              {toast.message}
            </Callout>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
