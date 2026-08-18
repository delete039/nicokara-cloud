import type { Announcement } from "@/types/announcement";

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
  if (!isRecord(value) || value.enabled !== true) return null;
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
  if (
    value.buttonLabel !== undefined &&
    !nonEmptyString(value.buttonLabel)
  ) {
    return null;
  }

  return {
    id: value.id.trim(),
    enabled: true,
    title: value.title.trim(),
    publishedAt: value.publishedAt?.trim(),
    content: value.content.map((paragraph) => paragraph.trim()),
    buttonLabel: value.buttonLabel?.trim() ?? "我知道了",
  };
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
