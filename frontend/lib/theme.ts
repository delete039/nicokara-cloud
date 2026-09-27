export type Theme = "light" | "dark";
export type ThemePreference = Theme | "system";

export const THEME_STORAGE_KEY = "nicokara:theme";
export const THEME_CHANGE_EVENT = "nicokara:theme-change";
export const THEME_MEDIA_QUERY = "(prefers-color-scheme: dark)";
export const THEME_PREFERENCE_DATA_ATTRIBUTE = "themePreference";

export function normalizeTheme(value: unknown): Theme {
  return value === "dark" ? "dark" : "light";
}

export function normalizeThemePreference(value: unknown): ThemePreference {
  if (value === "dark" || value === "light" || value === "system") return value;
  return "system";
}

export function resolveTheme(
  preference: unknown,
  systemTheme: Theme,
): Theme {
  const normalizedPreference = normalizeThemePreference(preference);
  return normalizedPreference === "system" ? normalizeTheme(systemTheme) : normalizedPreference;
}

export function getSystemTheme(): Theme {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return "light";
  }

  try {
    return window.matchMedia(THEME_MEDIA_QUERY).matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

// Apply the saved palette before the page content paints. An absent or invalid
// preference follows the device, while an existing light/dark value remains
// an explicit override for compatibility with previously saved settings.
export const THEME_INITIALIZATION_SCRIPT = `(() => {
  const root = document.documentElement;
  let storedPreference = null;
  try {
    storedPreference = localStorage.getItem("${THEME_STORAGE_KEY}");
  } catch {
    // Browser storage may be disabled; system detection still works below.
  }

  const preference = storedPreference === "dark" || storedPreference === "light" || storedPreference === "system"
    ? storedPreference
    : "system";
  let systemTheme = "light";
  try {
    systemTheme = typeof window !== "undefined"
      && typeof window.matchMedia === "function"
      && window.matchMedia("${THEME_MEDIA_QUERY}").matches
      ? "dark"
      : "light";
  } catch {
    // Older browsers without matchMedia use the light fallback.
  }

  root.dataset.${THEME_PREFERENCE_DATA_ATTRIBUTE} = preference;
  root.dataset.theme = preference === "system" ? systemTheme : preference;
})();`;
