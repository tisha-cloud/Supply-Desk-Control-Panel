"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import {
  Database,
  FileSearch,
  LayoutDashboard,
  Menu,
  Presentation,
  X,
} from "lucide-react";
import { backend } from "@/lib/backend";
import { isSupabaseConfigured } from "@/lib/supabase/client";
import { ThemeToggle } from "./ThemeToggle";

const LINKS = [
  { href: "/", label: "Overview", icon: LayoutDashboard, hint: "Portfolio at a glance" },
  { href: "/extraction", label: "Extraction", icon: FileSearch, hint: "Read landlord documents" },
  { href: "/data", label: "Supply Database", icon: Database, hint: "Buildings, spaces, photos" },
  { href: "/decks", label: "Deck Builder", icon: Presentation, hint: "Prompt to PowerPoint" },
];

function ConnectionDot() {
  const { data, error } = useSWR("backend-health", () => backend.health(), {
    shouldRetryOnError: false,
    refreshInterval: 30_000,
  });

  const supabaseReady = isSupabaseConfigured() && data?.supabase_configured;
  const state = error || !data ? "offline" : supabaseReady ? "ready" : "partial";

  const copy = {
    ready: { label: "All systems connected", tone: "bg-positive" },
    partial: { label: "Backend up · Supabase not configured", tone: "bg-warning" },
    offline: { label: "Backend unreachable on :8000", tone: "bg-danger" },
  }[state];

  return (
    <div
      className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-ink-2"
      title={copy.label}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${copy.tone}`} aria-hidden />
      <span className="hidden truncate lg:inline">{copy.label}</span>
    </div>
  );
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <>
      <Link
        href="/"
        onClick={onNavigate}
        className="flex items-center gap-2.5 px-3 py-1"
      >
        <span
          className="grid h-8 w-8 place-items-center rounded-lg text-[11px] font-bold tracking-tight text-white"
          style={{ background: "var(--accent)" }}
        >
          BLR
        </span>
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold">Control Panel</span>
          <span className="block truncate text-xs text-ink-3">Commercial supply</span>
        </span>
      </Link>

      <nav className="mt-6 flex-1 space-y-0.5">
        {LINKS.map(({ href, label, icon: Icon, hint }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={`group flex items-start gap-3 rounded-lg px-3 py-2 transition-colors ${
                active ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-surface-2 hover:text-ink"
              }`}
            >
              <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <span className="min-w-0">
                <span className="block text-sm font-medium">{label}</span>
                <span
                  className={`block truncate text-xs ${active ? "text-accent/70" : "text-ink-3"}`}
                >
                  {hint}
                </span>
              </span>
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-border pt-3">
        <ConnectionDot />
      </div>
    </>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex min-h-full">
      {/* ------------------------------------------------ desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-r border-border bg-surface px-3 py-4 md:flex">
        <SidebarContent />
      </aside>

      {/* ------------------------------------------------- mobile drawer */}
      {open ? (
        <div className="fixed inset-0 z-40 md:hidden">
          <button
            className="absolute inset-0 bg-black/40 backdrop-blur-[2px]"
            aria-label="Close navigation"
            onClick={() => setOpen(false)}
          />
          <aside className="animate-in absolute inset-y-0 left-0 flex w-64 flex-col border-r border-border bg-surface px-3 py-4">
            <SidebarContent onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-surface/80 px-4 backdrop-blur-md sm:px-6">
          <button
            className="btn-ghost -ml-2 px-2 md:hidden"
            aria-label={open ? "Close navigation" : "Open navigation"}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <X className="h-5 w-5" aria-hidden /> : <Menu className="h-5 w-5" aria-hidden />}
          </button>
          <div className="flex-1" />
          <ThemeToggle />
        </header>

        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}
