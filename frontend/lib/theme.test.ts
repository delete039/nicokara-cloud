import { runInNewContext } from "node:vm";
import { describe, expect, it } from "vitest";

import {
  getSystemTheme,
  normalizeTheme,
  normalizeThemePreference,
  resolveTheme,
  THEME_INITIALIZATION_SCRIPT,
  THEME_MEDIA_QUERY,
} from "./theme";

describe("page theme", () => {
  it("accepts only the supported persisted palettes", () => {
    expect(normalizeTheme("dark")).toBe("dark");
    expect(normalizeTheme("light")).toBe("light");
    expect(normalizeTheme(null)).toBe("light");
    expect(normalizeTheme("unknown")).toBe("light");
  });

  it("recognizes system as the default preference", () => {
    expect(normalizeThemePreference("system")).toBe("system");
    expect(normalizeThemePreference("dark")).toBe("dark");
    expect(normalizeThemePreference("light")).toBe("light");
    expect(normalizeThemePreference(null)).toBe("system");
    expect(normalizeThemePreference("unknown")).toBe("system");
  });

  it("uses the system palette only for the system preference", () => {
    expect(resolveTheme("system", "dark")).toBe("dark");
    expect(resolveTheme("system", "light")).toBe("light");
    expect(resolveTheme("dark", "light")).toBe("dark");
    expect(resolveTheme("light", "dark")).toBe("light");
    expect(resolveTheme("invalid", "dark")).toBe("dark");
  });

  it("detects the browser system palette when available", () => {
    const originalWindow = globalThis.window;
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: { matchMedia: (query: string) => ({ matches: query === THEME_MEDIA_QUERY }) },
    });
    expect(getSystemTheme()).toBe("dark");

    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: { matchMedia: () => ({ matches: false }) },
    });
    expect(getSystemTheme()).toBe("light");

    if (originalWindow === undefined) {
      Reflect.deleteProperty(globalThis, "window");
    } else {
      Object.defineProperty(globalThis, "window", { configurable: true, value: originalWindow });
    }
  });

  it("restores an explicit dark palette before hydration", () => {
    const document = { documentElement: { dataset: { theme: "light" } as Record<string, string> } };
    runInNewContext(THEME_INITIALIZATION_SCRIPT, {
      document,
      localStorage: { getItem: () => "dark" },
      window: { matchMedia: () => ({ matches: false }) },
    });
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.themePreference).toBe("dark");
  });

  it("follows the system palette when no preference is stored", () => {
    const document = { documentElement: { dataset: { theme: "light" } as Record<string, string> } };
    runInNewContext(THEME_INITIALIZATION_SCRIPT, {
      document,
      localStorage: { getItem: () => null },
      window: { matchMedia: () => ({ matches: true }) },
    });
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.themePreference).toBe("system");
  });

  it("still follows the system palette when access to storage is denied", () => {
    const document = { documentElement: { dataset: { theme: "" } as Record<string, string> } };
    runInNewContext(THEME_INITIALIZATION_SCRIPT, {
      document,
      localStorage: { getItem: () => { throw new Error("Storage disabled"); } },
      window: { matchMedia: () => ({ matches: true }) },
    });
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.themePreference).toBe("system");
  });

  it("uses the light fallback when system detection is unavailable", () => {
    const document = { documentElement: { dataset: { theme: "dark" } as Record<string, string> } };
    runInNewContext(THEME_INITIALIZATION_SCRIPT, {
      document,
      localStorage: { getItem: () => null },
    });
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.dataset.themePreference).toBe("system");
  });
});
