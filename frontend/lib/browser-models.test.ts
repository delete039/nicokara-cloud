import { describe, expect, it } from "vitest";

async function loadBrowserModels() {
  const modulePath = "./browser-models";
  return import(/* @vite-ignore */ modulePath).catch(() => null);
}

describe("browser model manifest and cache", () => {
  it("lists UVR and Japanese CTC artifacts without embedding model weights", async () => {
    const browserModels = await loadBrowserModels();
    expect(browserModels, "browser model module should exist").not.toBeNull();
    if (!browserModels) return;

    expect(browserModels.BROWSER_MODEL_MANIFEST.map((model: { id: string }) => model.id)).toEqual([
      "uvr-mdxnet-karaoke-2",
      "reazon-wav2vec2-base-rs35kh-int8",
    ]);
    expect(browserModels.BROWSER_MODEL_MANIFEST[0]).toMatchObject({
      purpose: "VOCAL_SEPARATION",
      estimatedBytes: 50_300_000,
      availability: "ADAPTER_PENDING",
    });
    expect(browserModels.BROWSER_MODEL_MANIFEST[1]).toMatchObject({
      purpose: "CTC_ALIGNMENT",
      estimatedBytes: 100_000_000,
      availability: "ADAPTER_PENDING",
    });
    expect(JSON.stringify(browserModels.BROWSER_MODEL_MANIFEST)).not.toContain("base64");
  });

  it("exposes a cache contract that can report model readiness", async () => {
    const browserModels = await loadBrowserModels();
    expect(browserModels).not.toBeNull();
    if (!browserModels) return;

    const cache = browserModels.createMemoryModelCache();
    expect(await browserModels.areRequiredModelsCached(cache)).toBe(false);

    for (const model of browserModels.BROWSER_MODEL_MANIFEST) {
      await cache.put(model.id, new Blob([model.id]));
    }

    expect(await browserModels.areRequiredModelsCached(cache)).toBe(true);
    expect(await cache.get("uvr-mdxnet-karaoke-2")).toBeInstanceOf(Blob);
  });
});
