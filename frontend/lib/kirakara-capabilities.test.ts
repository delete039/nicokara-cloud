import { describe, expect, it, vi } from "vitest";

import {
  detectKirakaraCapabilities,
  kirakaraSupportMessage,
} from "./kirakara-capabilities";

describe("detectKirakaraCapabilities", () => {
  it("selects a bounded mobile H.264 profile when WebCodecs is supported", async () => {
    const capabilities = await detectKirakaraCapabilities(
      {
        VideoEncoder: {
          isConfigSupported: vi.fn().mockResolvedValue({ supported: true }),
        },
        VideoDecoder: class {},
        VideoFrame: class {},
      },
      true,
    );

    expect(capabilities).toMatchObject({
      preview: true,
      export: true,
      profile: {
        codec: "avc1.42E01E",
        width: 1280,
        height: 720,
        framerate: 30,
      },
    });
  });

  it("keeps preview available but disables export without WebCodecs", async () => {
    await expect(detectKirakaraCapabilities({}, false)).resolves.toEqual({
      preview: true,
      export: false,
      reason: "WEBCODECS_UNAVAILABLE",
      profile: null,
    });
  });

  it("explains supported browsers and the cloud fallback when export is unavailable", () => {
    const message = kirakaraSupportMessage({
      preview: true,
      export: false,
      reason: "WEBCODECS_UNAVAILABLE",
      profile: null,
    });

    expect(message).toContain("Chrome");
    expect(message).toContain("Edge");
    expect(message).toContain("Safari");
    expect(message).toContain("云端渲染");
  });
});
