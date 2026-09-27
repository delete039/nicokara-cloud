"use client";

import { useEffect } from "react";

import {
  getSystemTheme,
  normalizeThemePreference,
  resolveTheme,
  THEME_CHANGE_EVENT,
  THEME_MEDIA_QUERY,
  THEME_PREFERENCE_DATA_ATTRIBUTE,
  THEME_STORAGE_KEY,
  type ThemePreference,
} from "@/lib/theme";

export function ThemeSync() {
  useEffect(() => {
    const root = document.documentElement;
    const mediaQuery = typeof window.matchMedia === "function"
      ? window.matchMedia(THEME_MEDIA_QUERY)
      : null;

    function applyPreference(preference: ThemePreference) {
      root.dataset[THEME_PREFERENCE_DATA_ATTRIBUTE] = preference;
      root.dataset.theme = resolveTheme(preference, getSystemTheme());
    }

    function notify() {
      window.dispatchEvent(new Event(THEME_CHANGE_EVENT));
    }

    function onStorage(event: StorageEvent) {
      if (event.key !== THEME_STORAGE_KEY && event.key !== null) return;
      applyPreference(normalizeThemePreference(event.newValue));
      notify();
    }

    function onSystemThemeChange() {
      if (normalizeThemePreference(root.dataset[THEME_PREFERENCE_DATA_ATTRIBUTE]) !== "system") return;
      applyPreference("system");
      notify();
    }

    const initialTheme = root.dataset.theme;
    applyPreference(normalizeThemePreference(root.dataset[THEME_PREFERENCE_DATA_ATTRIBUTE]));
    if (root.dataset.theme !== initialTheme) notify();
    window.addEventListener("storage", onStorage);
    if (mediaQuery) {
      if (typeof mediaQuery.addEventListener === "function") {
        mediaQuery.addEventListener("change", onSystemThemeChange);
      } else {
        mediaQuery.addListener?.(onSystemThemeChange);
      }
    }

    return () => {
      window.removeEventListener("storage", onStorage);
      if (!mediaQuery) return;
      if (typeof mediaQuery.removeEventListener === "function") {
        mediaQuery.removeEventListener("change", onSystemThemeChange);
      } else {
        mediaQuery.removeListener?.(onSystemThemeChange);
      }
    };
  }, []);

  return null;
}
