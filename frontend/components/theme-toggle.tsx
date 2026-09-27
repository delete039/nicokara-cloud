"use client";

import { ChevronDown, Monitor, Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

import {
  getSystemTheme,
  normalizeTheme,
  normalizeThemePreference,
  resolveTheme,
  THEME_CHANGE_EVENT,
  THEME_PREFERENCE_DATA_ATTRIBUTE,
  THEME_STORAGE_KEY,
  type ThemePreference,
} from "@/lib/theme";

function subscribe(onChange: () => void) {
  function onStorage(event: StorageEvent) {
    if (event.key !== THEME_STORAGE_KEY && event.key !== null) return;
    const preference = normalizeThemePreference(event.newValue);
    document.documentElement.dataset[THEME_PREFERENCE_DATA_ATTRIBUTE] = preference;
    document.documentElement.dataset.theme = resolveTheme(preference, getSystemTheme());
    onChange();
  }

  window.addEventListener(THEME_CHANGE_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(THEME_CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

function getSnapshot(): string {
  const preference = normalizeThemePreference(document.documentElement.dataset[THEME_PREFERENCE_DATA_ATTRIBUTE]);
  const theme = normalizeTheme(document.documentElement.dataset.theme);
  return `${preference}:${theme}`;
}

function getServerSnapshot(): string {
  return "system:light";
}

function selectTheme(preference: ThemePreference) {
  document.documentElement.dataset[THEME_PREFERENCE_DATA_ATTRIBUTE] = preference;
  document.documentElement.dataset.theme = resolveTheme(preference, getSystemTheme());
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Theme changes remain available when browser storage is disabled.
  }
  window.dispatchEvent(new Event(THEME_CHANGE_EVENT));
}

export function ThemeToggle() {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const [preference, theme] = snapshot.split(":") as [ThemePreference, "light" | "dark"];
  const Icon = preference === "system" ? Monitor : theme === "dark" ? Moon : Sun;

  return (
    <div className="focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 focus-within:ring-offset-background relative inline-flex min-h-10 shrink-0 items-center rounded-md border bg-card text-muted-foreground transition-colors hover:bg-muted">
      <Icon className="pointer-events-none ml-3 size-4" aria-hidden="true" />
      <select
        aria-label="主题模式"
        title="主题模式"
        value={preference}
        onChange={(event) => selectTheme(normalizeThemePreference(event.target.value))}
        className="min-h-10 appearance-none bg-transparent py-2 pl-2 pr-8 text-sm font-medium text-foreground outline-none"
      >
        <option value="system">跟随系统</option>
        <option value="light">浅色主题</option>
        <option value="dark">深色主题</option>
      </select>
      <ChevronDown className="pointer-events-none absolute right-2 size-4" aria-hidden="true" />
    </div>
  );
}
