import type { Announcement, AnnouncementBundle } from "@/types/announcement";

export const ANNOUNCEMENT_CONFIG_URL = "/announcement.json";
export const ANNOUNCEMENT_OPEN_EVENT = "nicokara:announcement:open";
const STORAGE_PREFIX = "nicokara:announcement:seen:";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

export function parseAnnouncement(value: unknown): Announcement | null {
  return parseAnnouncementRecord(value, true);
}

function parseAnnouncementRecord(
  value: unknown,
  requireEnabled: boolean,
): Announcement | null {
  if (!isRecord(value) || (requireEnabled && value.enabled !== true)) return null;
  if (!nonEmptyString(value.id) || !nonEmptyString(value.title)) return null;
  if (
    !Array.isArray(value.content) ||
    value.content.length === 0 ||
    !value.content.every(nonEmptyString)
  ) {
    return null;
  }
  if (
    value.publishedAt !== undefined &&
    !nonEmptyString(value.publishedAt)
  ) {
    return null;
  }
  if (value.version !== undefined && !nonEmptyString(value.version)) {
    return null;
  }
  if (
    value.buttonLabel !== undefined &&
    !nonEmptyString(value.buttonLabel)
  ) {
    return null;
  }

  const version = value.version?.trim();
  return {
    id: value.id.trim(),
    enabled: true,
    title: value.title.trim(),
    ...(version ? { version } : {}),
    publishedAt: value.publishedAt?.trim(),
    content: value.content.map((paragraph) => paragraph.trim()),
    buttonLabel: value.buttonLabel?.trim() ?? "我知道了",
  };
}

export function parseAnnouncementBundle(value: unknown): AnnouncementBundle | null {
  const current = parseAnnouncement(value);
  if (!current) return null;

  const rawHistory = isRecord(value) && Array.isArray(value.history)
    ? value.history
    : [];
  const history: Announcement[] = [];
  const seenIds = new Set([current.id]);
  for (const item of rawHistory) {
    const parsed = parseAnnouncementRecord(item, false);
    if (!parsed || seenIds.has(parsed.id)) continue;
    seenIds.add(parsed.id);
    history.push(parsed);
  }
  history.sort((left, right) => {
    const leftDate = left.publishedAt ?? "";
    const rightDate = right.publishedAt ?? "";
    return rightDate.localeCompare(leftDate);
  });
  return { current, history };
}

export function announcementStorageKey(id: string): string {
  return `${STORAGE_PREFIX}${id}`;
}

export function hasSeenAnnouncement(
  storage: Pick<Storage, "getItem">,
  id: string,
): boolean {
  return storage.getItem(announcementStorageKey(id)) === "1";
}

export function markAnnouncementSeen(
  storage: Pick<Storage, "setItem">,
  id: string,
): void {
  storage.setItem(announcementStorageKey(id), "1");
}
