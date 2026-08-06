import { readFile } from "node:fs/promises";

import { describe, expect, it } from "vitest";

describe("docker-compose.dev.yml", () => {
  it("runs Vinext on a glibc-compatible Node image", async () => {
    const compose = await readFile(
      new URL("../../docker-compose.dev.yml", import.meta.url),
      "utf8",
    );

    expect(compose).toContain(
      "npm run dev -- --hostname 0.0.0.0 --port 3000",
    );
    expect(compose).toContain("image: node:24-bookworm-slim");
    expect(compose).toContain('.nicokara-bookworm-$${LOCK_HASH}');
    expect(compose).not.toContain(
      "npm run dev -- --host 0.0.0.0 --port 3000",
    );
    expect(compose).not.toContain("npx next dev");
    expect(compose).not.toContain("image: node:24-alpine");
  });
});
