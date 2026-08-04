import type { ServerOptions } from "vite";

type DevServerConfigOptions = {
  backendOrigin: string | undefined;
  usePolling: boolean;
};

export function devServerConfig({
  backendOrigin,
  usePolling,
}: DevServerConfigOptions): ServerOptions {
  const target = new URL(
    backendOrigin || "http://127.0.0.1:8000",
  ).origin;

  return {
    proxy: {
      "/api": {
        target,
        changeOrigin: true,
      },
    },
    watch: usePolling
      ? { useFsEvents: false, usePolling: true }
      : undefined,
  };
}
