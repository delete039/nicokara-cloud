import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  announcementStorageKey,
  hasSeenAnnouncement,
  markAnnouncementSeen,
  parseAnnouncementBundle,
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
    expect(announcement).toMatchObject({
      id: "2026-10-01-update-v1",
      title: "2026-10-01 更新日志",
      version: "v4.1",
      publishedAt: "2026-10-01",
      buttonLabel: "わかった",
    });
    expect(announcement?.content).toEqual([
      "更新内容：",
      "1. 加入了可选的双注音生成功能。",
      "2. 支持导入多标准视频格式",
      "3. 修复了一些已知的问题。",
      "QQ 交流群",
      "欢迎加入ニコカラ自动生成器 QQ 交流群：1101583605。",
      "群内可交流使用问题、反馈建议和获取项目更新。",
    ]);
    const bundle = parseAnnouncementBundle(config);
    expect(bundle?.history.map(({ id }) => id)).toEqual([
      "2026-09-21-update-v1",
      "2026-09-04-update-v1",
      "2026-08-28-update-v1",
      "2026-08-18-update-v1",
      "2026-08-12-update-v1",
      "2026-08-11-update-v1",
      "2026-08-07-update-v1",
      "2026-08-06-update-v1",
      "2026-08-06-qq-group-v1",
    ]);
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
    expect(
      parseAnnouncement({
        id: "notice-1",
        enabled: true,
        title: "服务公告",
        version: " ",
        content: ["内容"],
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

  it("parses the current announcement together with deduplicated history", () => {
    expect(
      parseAnnouncementBundle({
        id: "current",
        enabled: true,
        title: "当前公告",
        content: ["当前内容"],
        history: [
          {
            id: "older",
            title: "旧公告",
            publishedAt: "2026-08-01",
            content: ["旧内容"],
          },
          {
            id: "current",
            title: "重复当前公告",
            content: ["不应重复"],
          },
        ],
      }),
    ).toEqual({
      current: {
        id: "current",
        enabled: true,
        title: "当前公告",
        publishedAt: undefined,
        content: ["当前内容"],
        buttonLabel: "我知道了",
      },
      history: [{
        id: "older",
        enabled: true,
        title: "旧公告",
        publishedAt: "2026-08-01",
        content: ["旧内容"],
        buttonLabel: "我知道了",
      }],
    });
  });
});
