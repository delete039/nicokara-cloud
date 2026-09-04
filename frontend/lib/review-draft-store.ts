import {
  splitReadingMoras,
  type KirakaraTimeline,
} from "@/lib/kirakara-timeline";
import type { ProcessedLyrics } from "@/types/job";

export type ReviewDraftKind = "readings" | "timeline";

export type ReviewDraftRecord = {
  key: string;
  jobId: string;
  kind: ReviewDraftKind;
  schemaVersion: 1;
  updatedAt: string;
  value: unknown;
};

export interface ReviewDraftBackend {
  get(key: string): Promise<ReviewDraftRecord | null>;
  put(record: ReviewDraftRecord): Promise<void>;
  delete(key: string): Promise<void>;
}

const DATABASE_NAME = "nicokara-review-drafts";
const STORE_NAME = "drafts";
const SCHEMA_VERSION = 1;

function draftKey(jobId: string, kind: ReviewDraftKind) {
  return `${jobId}:${kind}`;
}

export class ReviewDraftStore {
  constructor(private readonly backend: ReviewDraftBackend) {}

  async save<T>(
    jobId: string,
    kind: ReviewDraftKind,
    value: T,
  ): Promise<void> {
    await this.backend.put({
      key: draftKey(jobId, kind),
      jobId,
      kind,
      schemaVersion: SCHEMA_VERSION,
      updatedAt: new Date().toISOString(),
      value,
    });
  }

  async load<T>(jobId: string, kind: ReviewDraftKind): Promise<T | null> {
    const record = await this.backend.get(draftKey(jobId, kind));
    if (
      !record
      || record.jobId !== jobId
      || record.kind !== kind
      || record.schemaVersion !== SCHEMA_VERSION
    ) {
      return null;
    }
    return record.value as T;
  }

  async delete(jobId: string, kind: ReviewDraftKind): Promise<void> {
    await this.backend.delete(draftKey(jobId, kind));
  }
}

class IndexedDbReviewDraftBackend implements ReviewDraftBackend {
  private databasePromise: Promise<IDBDatabase | null> | null = null;

  private open(): Promise<IDBDatabase | null> {
    if (this.databasePromise) return this.databasePromise;
    this.databasePromise = new Promise((resolve) => {
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
    return this.databasePromise;
  }

  async get(key: string): Promise<ReviewDraftRecord | null> {
    const database = await this.open();
    if (!database) return null;
    return new Promise((resolve, reject) => {
      const request = database
        .transaction(STORE_NAME, "readonly")
        .objectStore(STORE_NAME)
        .get(key);
      request.onsuccess = () => {
        resolve((request.result as ReviewDraftRecord | undefined) ?? null);
      };
      request.onerror = () => reject(request.error);
    });
  }

  async put(record: ReviewDraftRecord): Promise<void> {
    const database = await this.open();
    if (!database) return;
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readwrite");
      transaction.objectStore(STORE_NAME).put(record);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  }

  async delete(key: string): Promise<void> {
    const database = await this.open();
    if (!database) return;
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readwrite");
      transaction.objectStore(STORE_NAME).delete(key);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function compatibleReadingDraft(
  source: ProcessedLyrics,
  candidate: unknown,
): ProcessedLyrics | null {
  if (!isRecord(candidate) || !Array.isArray(candidate.lines)) return null;
  if (candidate.lines.length !== source.lines.length) return null;
  for (let lineIndex = 0; lineIndex < source.lines.length; lineIndex += 1) {
    const sourceLine = source.lines[lineIndex];
    const candidateLine = candidate.lines[lineIndex];
    if (!isRecord(candidateLine) || candidateLine.surface !== sourceLine.surface) {
      return null;
    }
    if (
      !Array.isArray(candidateLine.tokens)
      || candidateLine.tokens.length !== sourceLine.tokens.length
    ) {
      return null;
    }
    for (let tokenIndex = 0; tokenIndex < sourceLine.tokens.length; tokenIndex += 1) {
      const token = candidateLine.tokens[tokenIndex];
      if (
        !isRecord(token)
        || token.surface !== sourceLine.tokens[tokenIndex].surface
        || typeof token.reading !== "string"
      ) {
        return null;
      }
    }
  }
  return candidate as ProcessedLyrics;
}

function sameTimelineStructure(
  source: KirakaraTimeline,
  candidate: unknown,
) {
  if (!isRecord(candidate) || !Array.isArray(candidate.lines)) return false;
  if (candidate.lines.length !== source.lines.length) return false;
  return source.lines.every((sourceLine, lineIndex) => {
    const candidateLine = candidate.lines[lineIndex];
    if (
      !isRecord(candidateLine)
      || typeof candidateLine.text !== "string"
      || typeof candidateLine.reading !== "string"
      || !Array.isArray(candidateLine.units)
      || candidateLine.units.length !== sourceLine.units.length
    ) {
      return false;
    }
    const unitsAreValid = sourceLine.units.every((_sourceUnit, unitIndex) => {
      const candidateUnit = candidateLine.units[unitIndex];
      if (
        !isRecord(candidateUnit)
        || typeof candidateUnit.text !== "string"
        || typeof candidateUnit.reading !== "string"
        || !Array.isArray(candidateUnit.moras)
      ) {
        return false;
      }
      const expectedMoras = splitReadingMoras(candidateUnit.reading);
      if (
        candidateUnit.moras.length > 0
        && candidateUnit.moras.length !== expectedMoras.length
      ) {
        return false;
      }
      return candidateUnit.moras.every(
        (_candidateMora, moraIndex) => {
          const candidateMora = candidateUnit.moras[moraIndex];
          return isRecord(candidateMora)
            && candidateMora.reading === expectedMoras[moraIndex];
        },
      );
    });
    return unitsAreValid
      && candidateLine.text === candidateLine.units
        .map((unit) => (unit as Record<string, unknown>).text)
        .join("")
      && candidateLine.reading === candidateLine.units
        .map((unit) => (unit as Record<string, unknown>).reading)
        .join("");
  });
}

function hasValidTimelineRanges(timeline: KirakaraTimeline) {
  const validRange = (start: number, end: number) =>
    Number.isFinite(start) && Number.isFinite(end) && start >= 0 && end >= start;
  return Number.isFinite(timeline.durationMs)
    && timeline.durationMs >= 0
    && timeline.lines.every((line) =>
      validRange(line.startMs, line.endMs)
      && line.units.every((unit) =>
        validRange(unit.startMs, unit.endMs)
        && unit.moras.every((mora) => validRange(mora.startMs, mora.endMs)),
      ),
    );
}

export function compatibleTimelineDraft(
  source: KirakaraTimeline,
  candidate: unknown,
): KirakaraTimeline | null {
  if (!isRecord(candidate) || !Array.isArray(candidate.lines)) return null;
  const timeline = candidate as KirakaraTimeline;
  return sameTimelineStructure(source, candidate) && hasValidTimelineRanges(timeline)
    ? timeline
    : null;
}

const browserReviewDraftStore = new ReviewDraftStore(
  new IndexedDbReviewDraftBackend(),
);

export async function loadBrowserReviewDraft<T>(
  jobId: string,
  kind: ReviewDraftKind,
): Promise<T | null> {
  try {
    return await browserReviewDraftStore.load<T>(jobId, kind);
  } catch {
    return null;
  }
}

export async function saveBrowserReviewDraft<T>(
  jobId: string,
  kind: ReviewDraftKind,
  value: T,
): Promise<void> {
  try {
    await browserReviewDraftStore.save(jobId, kind, value);
  } catch {
    // Browser storage is optional; editing must continue when it is unavailable.
  }
}

export async function deleteBrowserReviewDraft(
  jobId: string,
  kind: ReviewDraftKind,
): Promise<void> {
  try {
    await browserReviewDraftStore.delete(jobId, kind);
  } catch {
    // A stale local draft is safer than blocking the server-side workflow.
  }
}
