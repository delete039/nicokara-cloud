import type { ReviewedArtifactInspection } from "@/lib/reviewed-artifact-import";

export type UploadDraft = {
  video: File | null;
  lyricsText: string;
  lyricsFile: File | null;
  reviewedArtifacts: ReviewedArtifactInspection | null;
};

type UploadDraftRecord = {
  key: "current";
  schemaVersion: 1;
  updatedAt: string;
  value: UploadDraft;
};

const DATABASE_NAME = "nicokara-upload-drafts";
const STORE_NAME = "drafts";
const STORAGE_KEY = "nicokara.upload-draft.metadata";
const SCHEMA_VERSION = 1;

let memoryDraft: UploadDraft | null = null;
let databasePromise: Promise<IDBDatabase | null> | null = null;

function openDatabase(): Promise<IDBDatabase | null> {
  if (databasePromise) return databasePromise;
  databasePromise = new Promise((resolve) => {
    if (typeof indexedDB === "undefined") {
      resolve(null);
      return;
    }
    const request = indexedDB.open(DATABASE_NAME, SCHEMA_VERSION);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE_NAME)) {
        request.result.createObjectStore(STORE_NAME, { keyPath: "key" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => resolve(null);
    request.onblocked = () => resolve(null);
  });
  return databasePromise;
}

function rememberMetadata(draft: UploadDraft): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      lyricsText: draft.lyricsText,
      videoName: draft.video?.name ?? null,
      lyricsFileName: draft.lyricsFile?.name ?? null,
      reviewedArtifactNames: draft.reviewedArtifacts?.files.map((file) => file.name) ?? [],
      updatedAt: new Date().toISOString(),
    }));
  } catch {
    // Upload editing remains available when browser storage is disabled or full.
  }
}

export function rememberUploadDraft(draft: UploadDraft): void {
  memoryDraft = draft;
  rememberMetadata(draft);
}

export async function saveUploadDraft(draft: UploadDraft): Promise<void> {
  rememberUploadDraft(draft);
  const database = await openDatabase();
  if (!database) return;
  await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, "readwrite");
    transaction.objectStore(STORE_NAME).put({
      key: "current",
      schemaVersion: SCHEMA_VERSION,
      updatedAt: new Date().toISOString(),
      value: draft,
    } satisfies UploadDraftRecord);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}

export async function loadUploadDraft(): Promise<UploadDraft | null> {
  if (memoryDraft) return memoryDraft;
  const database = await openDatabase();
  if (database) {
    const stored = await new Promise<UploadDraftRecord | null>((resolve, reject) => {
      const request = database
        .transaction(STORE_NAME, "readonly")
        .objectStore(STORE_NAME)
        .get("current");
      request.onsuccess = () => resolve((request.result as UploadDraftRecord | undefined) ?? null);
      request.onerror = () => reject(request.error);
    }).catch(() => null);
    if (stored?.schemaVersion === SCHEMA_VERSION && stored.value) {
      memoryDraft = stored.value;
      return memoryDraft;
    }
  }

  try {
    const metadata = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null") as {
      lyricsText?: unknown;
    } | null;
    if (typeof metadata?.lyricsText === "string" && metadata.lyricsText) {
      memoryDraft = {
        video: null,
        lyricsText: metadata.lyricsText,
        lyricsFile: null,
        reviewedArtifacts: null,
      };
      return memoryDraft;
    }
  } catch {
    // Ignore malformed or unavailable local storage.
  }
  return null;
}

export async function clearUploadDraft(): Promise<void> {
  memoryDraft = null;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Clearing the draft is best effort.
  }
  const database = await openDatabase();
  if (!database) return;
  await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, "readwrite");
    transaction.objectStore(STORE_NAME).delete("current");
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  }).catch(() => undefined);
}
