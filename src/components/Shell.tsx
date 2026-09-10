"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import {
  Database,
  FileSearch,
  LayoutDashboard,
  LogOut,
  Menu,
  Presentation,
  ShieldCheck,
  X,
} from "lucide-react";
import { backend } from "@/lib/backend";
import { isSupabaseConfigured } from "@/lib/supabase/client";
import { useAccess } from "@/lib/access";
import { ThemeToggle } from "./ThemeToggle";

/**
 * Navigation, named for what each screen does.
 *
 * `permission` decides whether the link is shown at all: a viewer has no
 * business seeing a Document Intake tab that will refuse every action on it.
 */
const LINKS = [
  {
    href: "/",
    label: "Overview",
    icon: LayoutDashboard,
    hint: "Portfolio at a glance",
    permission: null,
  },
  {
    href: "/extraction",
    label: "Document Intake",
    icon: FileSearch,
    hint: "Read landlord files into stock",
    permission: "intake.run",
  },
  {
    href: "/data",
    label: "Supply Inventory",
    icon: Database,
    hint: "Buildings, availability, photos",
    permission: "supply.read",
  },
  {
    href: "/decks",
    label: "Proposal Builder",
    icon: Presentation,
    hint: "Requirement to PowerPoint or Excel",
    permission: "proposals.write",
  },
  {
    href: "/access",
    label: "User Access",
    icon: ShieldCheck,
    hint: "People, roles and permissions",
    permission: "users.manage",
  },
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
    offline: { label: "Backend unreachable", tone: "bg-danger" },
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
  const { can } = useAccess();
  const visible = LINKS.filter((link) => !link.permission || can(link.permission));

  return (
    <>
      <Link href="/" onClick={onNavigate} className="flex items-center gap-2.5 px-3 py-1">
        <span
          className="grid h-8 w-8 place-items-center rounded-lg text-[11px] font-bold tracking-tight text-white"
          style={{ background: "var(--accent)" }}
        >
          BLR
        </span>
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold">Supply Desk</span>
          <span className="block truncate text-xs text-ink-3">Bengaluru commercial</span>
        </span>
      </Link>

      <nav className="mt-6 flex-1 space-y-0.5">
        {visible.map(({ href, label, icon: Icon, hint }) => {
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

function AccountMenu() {
  const { me, authReady, signOut } = useAccess();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function away(event: MouseEvent) {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  if (!authReady) {
    return (
      <span
        className="chip bg-warning-soft text-warning"
        title="Run supabase/migrations/0006_auth_and_roles.sql to switch authentication on"
      >
        Auth not enabled
      </span>
    );
  }
  if (!me) return null;

  const initials = (me.full_name || me.email)
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");

  return (
    <div className="relative" ref={box}>
      <button
        className="flex items-center gap-2 rounded-lg px-1.5 py-1 transition-colors hover:bg-surface-2"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="grid h-7 w-7 place-items-center rounded-full bg-accent-soft text-[11px] font-semibold text-accent">
          {initials || "?"}
        </span>
        <span className="hidden text-left sm:block">
          <span className="block max-w-[160px] truncate text-xs font-medium leading-tight">
            {me.full_name || me.email}
          </span>
          <span className="block text-[11px] leading-tight text-ink-3">{me.role}</span>
        </span>
      </button>

      {open ? (
        <div
          role="menu"
          className="animate-in absolute right-0 z-50 mt-1.5 w-60 rounded-xl border border-border bg-surface p-1.5 shadow-lg"
        >
          <div className="px-2.5 py-2">
            <p className="truncate text-sm font-medium">{me.full_name || "Signed in"}</p>
            <p className="truncate text-xs text-ink-3">{me.email}</p>
            <p className="mt-1.5 text-xs text-ink-2">
              Role <span className="font-medium text-ink">{me.role}</span> ·{" "}
              {me.permissions.includes("*")
                ? "full access"
                : `${me.permissions.length} permission${me.permissions.length === 1 ? "" : "s"}`}
            </p>
          </div>
          <div className="my-1 h-px bg-border" />
          <button
            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
            onClick={signOut}
          >
            <LogOut className="h-4 w-4" aria-hidden />
            Sign out
          </button>
        </div>
      ) : null}
    </div>
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

  // The sign-in screen has no navigation to show: there is nowhere to go yet.
  if (pathname === "/login") return <>{children}</>;

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
          <AccountMenu />
          <ThemeToggle />
        </header>

        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}
