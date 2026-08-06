import { describe, expect, it } from "vitest";

async function loadMobileProcessing() {
  const modulePath = "./mobile-processing";
  return import(/* @vite-ignore */ modulePath).catch(() => null);
}

const capablePhone = {
  isMobile: true,
  webAssembly: true,
  webGpu: true,
  audioExtraction: true,
  cacheStorage: true,
  crossOriginIsolated: true,
  hardwareConcurrency: 8,
  deviceMemoryGb: 8,
  storageAvailableBytes: 1024 * 1024 * 1024,
  requiredModelsCached: true,
};

const capableDesktop = {
  ...capablePhone,
  isMobile: false,
};

describe("mobile processing route selection", () => {
  it("keeps a 300 MB mobile video eligible for fully local processing", async () => {
    const mobileProcessing = await loadMobileProcessing();
    expect(mobileProcessing, "mobile processing module should exist").not.toBeNull();
    if (!mobileProcessing) return;

    expect(mobileProcessing.MAX_LOCAL_MEDIA_BYTES).toBe(300 * 1024 * 1024);
    expect(
      mobileProcessing.selectMobileProcessingRoute({
        videoSizeBytes: mobileProcessing.MAX_LOCAL_MEDIA_BYTES,
        capabilities: capablePhone,
      }),
    ).toBe("LOCAL");
  });

  it("uses audio-only upload when local inference models are unavailable", async () => {
    const mobileProcessing = await loadMobileProcessing();
    expect(mobileProcessing).not.toBeNull();
    if (!mobileProcessing) return;

    expect(
      mobileProcessing.selectMobileProcessingRoute({
        videoSizeBytes: 120 * 1024 * 1024,
        capabilities: {
          ...capablePhone,
          webGpu: false,
          requiredModelsCached: false,
        },
      }),
    ).toBe("AUDIO_ONLY");
  });

  it("uses audio-only upload on a desktop browser when local models are unavailable", async () => {
    const mobileProcessing = await loadMobileProcessing();
    expect(mobileProcessing).not.toBeNull();
    if (!mobileProcessing) return;

    expect(
      mobileProcessing.selectMobileProcessingRoute({
        videoSizeBytes: 120 * 1024 * 1024,
        capabilities: {
          ...capableDesktop,
          webGpu: false,
          requiredModelsCached: false,
        },
      }),
    ).toBe("AUDIO_ONLY");
  });

  it("keeps a capable desktop browser eligible for fully local processing", async () => {
    const mobileProcessing = await loadMobileProcessing();
    expect(mobileProcessing).not.toBeNull();
    if (!mobileProcessing) return;

    expect(
      mobileProcessing.selectMobileProcessingRoute({
        videoSizeBytes: 120 * 1024 * 1024,
        capabilities: capableDesktop,
      }),
    ).toBe("LOCAL");
  });

  it("falls back to remote video transport above the 300 MB local rule", async () => {
    const mobileProcessing = await loadMobileProcessing();
    expect(mobileProcessing).not.toBeNull();
    if (!mobileProcessing) return;

    expect(
      mobileProcessing.selectMobileProcessingRoute({
        videoSizeBytes: 300 * 1024 * 1024 + 1,
        capabilities: capablePhone,
      }),
    ).toBe("REMOTE_VIDEO");
  });

  it("falls back to remote video when the phone cannot extract audio", async () => {
    const mobileProcessing = await loadMobileProcessing();
    expect(mobileProcessing).not.toBeNull();
    if (!mobileProcessing) return;

    expect(
      mobileProcessing.selectMobileProcessingRoute({
        videoSizeBytes: 80 * 1024 * 1024,
        capabilities: {
          ...capablePhone,
          webAssembly: false,
          webGpu: false,
          audioExtraction: false,
          requiredModelsCached: false,
        },
      }),
    ).toBe("REMOTE_VIDEO");
  });

  it("uses audio-only extraction without requiring WebAssembly", async () => {
    const mobileProcessing = await loadMobileProcessing();
    expect(mobileProcessing).not.toBeNull();
    if (!mobileProcessing) return;

    expect(
      mobileProcessing.selectMobileProcessingRoute({
        videoSizeBytes: 80 * 1024 * 1024,
        capabilities: {
          ...capablePhone,
          webAssembly: false,
          webGpu: false,
          requiredModelsCached: false,
        },
      }),
    ).toBe("AUDIO_ONLY");
  });

  it("detects the file APIs required by the browser extraction adapter", async () => {
    const mobileProcessing = await loadMobileProcessing();
    expect(mobileProcessing).not.toBeNull();
    if (!mobileProcessing) return;

    expect(
      mobileProcessing.isBrowserAudioExtractionSupported({
        Blob: class {},
        File: class {},
        ArrayBuffer,
      }),
    ).toBe(true);
    expect(
      mobileProcessing.isBrowserAudioExtractionSupported({
        Blob: class {},
        ArrayBuffer,
      }),
    ).toBe(false);
  });
});
