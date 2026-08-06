export type BrowserModelPurpose = "VOCAL_SEPARATION" | "CTC_ALIGNMENT";
export type BrowserModelAvailability = "ADAPTER_PENDING" | "AVAILABLE";

export type BrowserModelDescriptor = {
  id: string;
  purpose: BrowserModelPurpose;
  artifactName: string;
  estimatedBytes: number;
  availability: BrowserModelAvailability;
  downloadUrl: string | null;
  sourceUrl: string;
};

export const BROWSER_MODEL_MANIFEST: readonly BrowserModelDescriptor[] = [
  {
    id: "uvr-mdxnet-karaoke-2",
    purpose: "VOCAL_SEPARATION",
    artifactName: "UVR_MDXNET_KARA_2.onnx",
    estimatedBytes: 50_300_000,
    availability: "ADAPTER_PENDING",
    downloadUrl: null,
    sourceUrl: "https://github.com/TRvlvr/model_repo",
  },
  {
    id: "reazon-wav2vec2-base-rs35kh-int8",
    purpose: "CTC_ALIGNMENT",
    artifactName: "reazon-wav2vec2-base-rs35kh-int8.onnx",
    estimatedBytes: 100_000_000,
    availability: "ADAPTER_PENDING",
    downloadUrl: null,
    sourceUrl:
      "https://huggingface.co/reazon-research/japanese-wav2vec2-base-rs35kh",
  },
] as const;

export interface ModelCache {
  get(modelId: string): Promise<Blob | null>;
  put(modelId: string, value: Blob): Promise<void>;
  remove(modelId: string): Promise<boolean>;
}

export function createMemoryModelCache(): ModelCache {
  const entries = new Map<string, Blob>();
  return {
    async get(modelId) {
      return entries.get(modelId) ?? null;
    },
    async put(modelId, value) {
      entries.set(modelId, value);
    },
    async remove(modelId) {
      return entries.delete(modelId);
    },
  };
}

function modelCacheRequest(modelId: string): Request {
  return new Request(
    `${globalThis.location.origin}/__nicokara_models__/${encodeURIComponent(modelId)}`,
  );
}

export function createBrowserModelCache(
  cacheStorage: CacheStorage = globalThis.caches,
): ModelCache {
  const cacheName = "nicokara-browser-models-v1";
  return {
    async get(modelId) {
      const cache = await cacheStorage.open(cacheName);
      const response = await cache.match(modelCacheRequest(modelId));
      return response ? response.blob() : null;
    },
    async put(modelId, value) {
      const cache = await cacheStorage.open(cacheName);
      await cache.put(modelCacheRequest(modelId), new Response(value));
    },
    async remove(modelId) {
      const cache = await cacheStorage.open(cacheName);
      return cache.delete(modelCacheRequest(modelId));
    },
  };
}

export async function areRequiredModelsCached(
  cache: ModelCache,
): Promise<boolean> {
  const cached = await Promise.all(
    BROWSER_MODEL_MANIFEST.map((model) => cache.get(model.id)),
  );
  return cached.every((value) => value !== null && value.size > 0);
}

export const REQUIRED_MODEL_BYTES = BROWSER_MODEL_MANIFEST.reduce(
  (total, model) => total + model.estimatedBytes,
  0,
);
