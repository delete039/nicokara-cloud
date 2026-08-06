import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  announcementStorageKey,
  hasSeenAnnouncement,
  markAnnouncementSeen,
  parseAnnouncement,
} from "./announcement";

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  };
}

describe("announcement configuration", () => {
  it("keeps the deployed announcement file valid", () => {
    const config = JSON.parse(
      readFileSync(
        new URL("../public/announcement.json", import.meta.url),
        "utf-8",
      ),
    );

    const announcement = parseAnnouncement(config);

    expect(announcement).not.toBeNull();
    expect(announcement?.id.length).toBeGreaterThan(0);
  });

  it("parses enabled plain-text announcements", () => {
    expect(
      parseAnnouncement({
        id: "notice-1",
        enabled: true,
        title: " 服务公告 ",
        content: [" 第一段 ", "第二段"],
      }),
    ).toEqual({
      id: "notice-1",
      enabled: true,
      title: "服务公告",
      publishedAt: undefined,
      content: ["第一段", "第二段"],
      buttonLabel: "我知道了",
    });
  });

  it("ignores disabled or malformed announcements", () => {
    expect(
      parseAnnouncement({
        id: "notice-1",
        enabled: false,
        title: "服务公告",
        content: ["内容"],
      }),
    ).toBeNull();
    expect(
      parseAnnouncement({
        id: "notice-1",
        enabled: true,
        title: "服务公告",
        content: [],
      }),
    ).toBeNull();
  });

  it("records each announcement id independently", () => {
    const storage = memoryStorage();

    expect(hasSeenAnnouncement(storage, "notice-1")).toBe(false);
    markAnnouncementSeen(storage, "notice-1");
    expect(hasSeenAnnouncement(storage, "notice-1")).toBe(true);
    expect(hasSeenAnnouncement(storage, "notice-2")).toBe(false);
    expect(announcementStorageKey("notice-1")).toContain("notice-1");
  });
});
