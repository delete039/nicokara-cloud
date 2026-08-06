import {
  REQUIRED_MODEL_BYTES,
  areRequiredModelsCached,
  createBrowserModelCache,
  type ModelCache,
} from "@/lib/browser-models";

export const MAX_LOCAL_MEDIA_BYTES = 300 * 1024 * 1024;
export const BROWSER_AUDIO_EXTRACTION_ADAPTER_READY = true;

export type MobileProcessingRoute = "LOCAL" | "AUDIO_ONLY" | "REMOTE_VIDEO";

export type MobileCapabilities = {
  isMobile: boolean;
  webAssembly: boolean;
  webGpu: boolean;
  audioExtraction: boolean;
  cacheStorage: boolean;
  crossOriginIsolated: boolean;
  hardwareConcurrency: number;
  deviceMemoryGb: number | null;
  storageAvailableBytes: number | null;
  requiredModelsCached: boolean;
};

type NavigatorWithCapabilities = Navigator & {
  deviceMemory?: number;
  gpu?: unknown;
  userAgentData?: { mobile?: boolean };
  storage?: StorageManager;
};

export type MobileProcessingSelection = {
  videoSizeBytes: number;
  capabilities: MobileCapabilities;
};

function hasEnoughLocalStorage(
  availableBytes: number | null,
  videoSizeBytes: number,
): boolean {
  if (availableBytes === null) return false;
  return availableBytes >= videoSizeBytes * 2 + REQUIRED_MODEL_BYTES;
}

export function selectMobileProcessingRoute({
  videoSizeBytes,
  capabilities,
}: MobileProcessingSelection): MobileProcessingRoute {
  if (
    videoSizeBytes <= 0 ||
    videoSizeBytes > MAX_LOCAL_MEDIA_BYTES
  ) {
    return "REMOTE_VIDEO";
  }

  const canRunFullyLocal =
    capabilities.webAssembly &&
    capabilities.webGpu &&
    capabilities.audioExtraction &&
    capabilities.cacheStorage &&
    capabilities.crossOriginIsolated &&
    capabilities.requiredModelsCached &&
    capabilities.hardwareConcurrency >= 6 &&
    (capabilities.deviceMemoryGb ?? 0) >= 6 &&
    hasEnoughLocalStorage(
      capabilities.storageAvailableBytes,
      videoSizeBytes,
    );
  if (canRunFullyLocal) return "LOCAL";

  if (capabilities.audioExtraction) {
    return "AUDIO_ONLY";
  }
  return "REMOTE_VIDEO";
}

function isMobileNavigator(navigatorValue: NavigatorWithCapabilities): boolean {
  if (typeof navigatorValue.userAgentData?.mobile === "boolean") {
    return navigatorValue.userAgentData.mobile;
  }
  return /Android|iPhone|iPad|iPod|Mobile/i.test(navigatorValue.userAgent);
}

export async function detectMobileCapabilities(
  cache?: ModelCache,
): Promise<MobileCapabilities> {
  const navigatorValue = globalThis.navigator as NavigatorWithCapabilities;
  const webAssembly = typeof globalThis.WebAssembly === "object";
  const audioExtraction =
    BROWSER_AUDIO_EXTRACTION_ADAPTER_READY &&
    isBrowserAudioExtractionSupported(globalThis);
  const cacheStorage = "caches" in globalThis;
  let storageAvailableBytes: number | null = null;
  try {
    const estimate = await navigatorValue.storage?.estimate();
    if (estimate?.quota !== undefined) {
      storageAvailableBytes = Math.max(
        0,
        estimate.quota - (estimate.usage ?? 0),
      );
    }
  } catch {
    storageAvailableBytes = null;
  }

  let requiredModelsCached = false;
  if (cacheStorage) {
    try {
      requiredModelsCached = await areRequiredModelsCached(
        cache ?? createBrowserModelCache(),
      );
    } catch {
      requiredModelsCached = false;
    }
  }

  return {
    isMobile: isMobileNavigator(navigatorValue),
    webAssembly,
    webGpu: "gpu" in navigatorValue,
    audioExtraction,
    cacheStorage,
    crossOriginIsolated: globalThis.crossOriginIsolated === true,
    hardwareConcurrency: navigatorValue.hardwareConcurrency || 1,
    deviceMemoryGb: navigatorValue.deviceMemory ?? null,
    storageAvailableBytes,
    requiredModelsCached,
  };
}

export function isBrowserAudioExtractionSupported(
  scope: Record<string, unknown>,
): boolean {
  return (
    typeof scope.Blob === "function" &&
    typeof scope.File === "function" &&
    typeof scope.ArrayBuffer === "function"
  );
}
