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
    expect(announcement).toMatchObject({
      id: "2026-08-18-update-v1",
      title: "2026-08-18 更新日志",
      publishedAt: "2026-08-18",
      buttonLabel: "わかった",
    });
    expect(announcement?.content).toEqual([
      "2026-08-18",
      "新增功能",
      "1. 处理失败时可重新入队。",
      "2. 歌词导入时可自动检测长度是否可能超出幕布。",
      "问题修复",
      "1. 修复了云端渲染的一些问题。",
      "2. 修复了 ASS 文件导出错误的问题。",
      "3. 修复了 OFF VOCAL 导出失败的问题。",
      "QQ 交流群",
      "欢迎加入ニコカラ自动生成器 QQ 交流群：1101583605。",
      "群内可交流使用问题、反馈建议和获取项目更新。",
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
