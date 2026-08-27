import { describe, expect, it } from "vitest";

import type { KirakaraTimeline } from "./kirakara-timeline";
import {
  compatibleReadingDraft,
  compatibleTimelineDraft,
  ReviewDraftStore,
  type ReviewDraftBackend,
  type ReviewDraftRecord,
} from "./review-draft-store";
import type { ProcessedLyrics } from "@/types/job";

class MemoryDraftBackend implements ReviewDraftBackend {
  readonly records = new Map<string, ReviewDraftRecord>();

  async get(key: string): Promise<ReviewDraftRecord | null> {
    return this.records.get(key) ?? null;
  }

  async put(record: ReviewDraftRecord): Promise<void> {
    this.records.set(record.key, record);
  }

  async delete(key: string): Promise<void> {
    this.records.delete(key);
  }
}

const lyrics: ProcessedLyrics = {
  provider: "local",
  source_text: "君",
  warnings: [],
  lines: [{
    source: "君",
    surface: "君",
    reading: "きみ",
    tokens: [{ surface: "君", reading: "きみ" }],
  }],
};

const timeline: KirakaraTimeline = {
  confidence: 1,
  warnings: [],
  durationMs: 2000,
  lines: [{
    text: "君",
    reading: "きみ",
    startMs: 1000,
    endMs: 2000,
    units: [{
      text: "君",
      reading: "きみ",
      startMs: 1000,
      endMs: 2000,
      moras: [
        { reading: "き", startMs: 1000, endMs: 1500, matched: true },
        { reading: "み", startMs: 1500, endMs: 2000, matched: true },
      ],
    }],
  }],
};

describe("ReviewDraftStore", () => {
  it("keeps reading and timeline drafts separated by job and kind", async () => {
    const store = new ReviewDraftStore(new MemoryDraftBackend());

    await store.save("job-1", "readings", lyrics);
    await store.save("job-1", "timeline", timeline);

    await expect(store.load("job-1", "readings")).resolves.toEqual(lyrics);
    await expect(store.load("job-1", "timeline")).resolves.toEqual(timeline);
    await expect(store.load("job-2", "readings")).resolves.toBeNull();
  });

  it("restores drafts only when the lyric structure still matches", () => {
    const edited = structuredClone(lyrics);
    edited.lines[0].tokens[0].reading = "くん";
    expect(compatibleReadingDraft(lyrics, edited)).toEqual(edited);

    const stale = structuredClone(edited);
    stale.lines[0].tokens[0].surface = "別";
    expect(compatibleReadingDraft(lyrics, stale)).toBeNull();
  });

  it("restores a valid adjusted mora timeline", () => {
    const edited = structuredClone(timeline);
    edited.lines[0].units[0].moras[0].endMs = 1400;
    edited.lines[0].units[0].moras[1].startMs = 1400;

    expect(compatibleTimelineDraft(timeline, edited)).toEqual(edited);
  });

  it("ignores incomplete browser data instead of interrupting editing", () => {
    expect(() => compatibleTimelineDraft(timeline, { lines: [{}] })).not.toThrow();
    expect(compatibleTimelineDraft(timeline, { lines: [{}] })).toBeNull();
    expect(compatibleReadingDraft(lyrics, { lines: [{}] })).toBeNull();
  });
});
