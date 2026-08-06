import { describe, expect, it } from "vitest";

import { devServerConfig } from "./dev-server";

describe("devServerConfig", () => {
  it("proxies the production-style API path to the local backend", () => {
    const config = devServerConfig({
      backendOrigin: undefined,
      usePolling: false,
    });

    expect(config.proxy?.["/api"]).toMatchObject({
      target: "http://127.0.0.1:8000",
      changeOrigin: true,
    });
  });

  it("allows the local backend origin to be overridden", () => {
    const config = devServerConfig({
      backendOrigin: "http://127.0.0.1:9000/",
      usePolling: true,
    });

    expect(config.proxy?.["/api"]).toMatchObject({
      target: "http://127.0.0.1:9000",
    });
    expect(config.watch).toMatchObject({
      useFsEvents: false,
      usePolling: true,
    });
  });

  it("enables cross-origin isolation for threaded browser inference", () => {
    const config = devServerConfig({
      backendOrigin: undefined,
      usePolling: false,
    });

    expect(config.headers).toMatchObject({
      "Cross-Origin-Opener-Policy": "same-origin",
      "Cross-Origin-Embedder-Policy": "require-corp",
    });
  });
});
