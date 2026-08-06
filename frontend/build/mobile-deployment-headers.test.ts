import { readFile } from "node:fs/promises";

import { describe, expect, it } from "vitest";

describe("mobile inference deployment headers", () => {
  it("configures standalone responses and both production deployment scripts", async () => {
    const nextConfigModule = await import("../next.config");
    const headers = await nextConfigModule.default.headers?.();
    expect(headers?.[0]).toMatchObject({ source: "/(.*)" });
    expect(headers?.[0].headers).toEqual(
      expect.arrayContaining([
        {
          key: "Cross-Origin-Opener-Policy",
          value: "same-origin",
        },
        {
          key: "Cross-Origin-Embedder-Policy",
          value: "require-corp",
        },
      ]),
    );

    const scripts = await Promise.all([
      readFile(
        new URL("../../release/deploy-nicokara-from-data.sh", import.meta.url),
        "utf8",
      ),
      readFile(
        new URL("../../release/resume-nicokara-after-pip.sh", import.meta.url),
        "utf8",
      ),
    ]);
    for (const script of scripts) {
      expect(script).toContain(
        "add_header Cross-Origin-Opener-Policy same-origin always;",
      );
      expect(script).toContain(
        "add_header Cross-Origin-Embedder-Policy require-corp always;",
      );
    }
  });
});
