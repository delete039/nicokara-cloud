// @vitest-environment jsdom
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  THEME_MEDIA_QUERY,
  THEME_PREFERENCE_DATA_ATTRIBUTE,
} from "@/lib/theme";

import { ThemeSync } from "./theme-sync";

type MediaQueryListener = (event: MediaQueryListEvent) => void;

function createMediaQueryList(initialMatches: boolean) {
  let matches = initialMatches;
  const listeners = new Set<MediaQueryListener>();
  const mediaQuery = {
    get matches() {
      return matches;
    },
    media: THEME_MEDIA_QUERY,
    onchange: null,
    addEventListener: (_type: string, listener: MediaQueryListener) => {
      listeners.add(listener);
    },
    removeEventListener: (_type: string, listener: MediaQueryListener) => {
      listeners.delete(listener);
    },
    addListener: (listener: MediaQueryListener) => {
      listeners.add(listener);
    },
    removeListener: (listener: MediaQueryListener) => {
      listeners.delete(listener);
    },
    dispatchEvent: () => true,
  } as unknown as MediaQueryList;

  return {
    mediaQuery,
    setMatches(nextMatches: boolean) {
      matches = nextMatches;
      const event = { matches, media: THEME_MEDIA_QUERY } as MediaQueryListEvent;
      listeners.forEach((listener) => listener(event));
    },
  };
}

describe("ThemeSync", () => {
  const originalMatchMedia = window.matchMedia;

  afterEach(() => {
    cleanup();
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("data-theme-preference");
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: originalMatchMedia,
    });
  });

  it("follows system changes and leaves manual choices fixed", async () => {
    const system = createMediaQueryList(false);
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn(() => system.mediaQuery),
    });
    document.documentElement.dataset[THEME_PREFERENCE_DATA_ATTRIBUTE] = "system";
    document.documentElement.dataset.theme = "light";

    await act(async () => {
      render(<ThemeSync />);
    });
    expect(document.documentElement.dataset.theme).toBe("light");

    await act(async () => {
      system.setMatches(true);
    });
    expect(document.documentElement.dataset.theme).toBe("dark");

    document.documentElement.dataset[THEME_PREFERENCE_DATA_ATTRIBUTE] = "light";
    document.documentElement.dataset.theme = "light";
    await act(async () => {
      system.setMatches(false);
      system.setMatches(true);
    });
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
