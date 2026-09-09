"use client";

import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

type Theme = "light" | "dark" | "system";

const OPTIONS: { value: Theme; icon: typeof Sun; label: string }[] = [
  { value: "light", icon: Sun, label: "Light" },
  { value: "system", icon: Monitor, label: "System" },
  { value: "dark", icon: Moon, label: "Dark" },
];

export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
  try {
    localStorage.setItem("theme", theme);
  } catch {
    /* private browsing - the choice just will not persist */
  }
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("system");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    try {
      const stored = localStorage.getItem("theme") as Theme | null;
      if (stored) setTheme(stored);
    } catch {
      /* ignore */
    }
  }, []);

  // Render the track before hydration so the header does not reflow.
  return (
    <div
      className="inline-flex items-center gap-0.5 rounded-lg border border-border bg-surface-2 p-0.5"
      role="group"
      aria-label="Colour theme"
    >
      {OPTIONS.map(({ value, icon: Icon, label }) => {
        const active = mounted && theme === value;
        return (
          <button
            key={value}
            type="button"
            aria-label={label}
            aria-pressed={active}
            title={label}
            onClick={() => {
              setTheme(value);
              applyTheme(value);
            }}
            className={`grid h-6 w-6 place-items-center rounded-md transition-colors ${
              active
                ? "bg-surface text-ink shadow-[var(--shadow-sm)]"
                : "text-ink-3 hover:text-ink"
            }`}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden />
          </button>
        );
      })}
    </div>
  );
}

/**
 * Runs before first paint so a dark-mode user never sees a white flash.
 * Kept as a raw string because it must execute ahead of hydration.
 */
export const themeScript = `
(function () {
  try {
    var t = localStorage.getItem('theme');
    if (t === 'dark' || t === 'light') document.documentElement.setAttribute('data-theme', t);
  } catch (e) {}
})();
`;
