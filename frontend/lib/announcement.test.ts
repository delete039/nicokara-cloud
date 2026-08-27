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
      id: "2026-08-28-update-v1",
      title: "2026-08-28 更新日志",
      publishedAt: "2026-08-28",
      buttonLabel: "わかった",
    });
    expect(announcement?.content).toEqual([
      "新增功能",
      "1. 支持导入本站导出的调整数据，包括注音数据、Mora 时间轴和 ASS 字幕。",
      "2. 本地导出可切换为云端视频导出。",
      "3. 时间轴编辑页面新增功能，可以返回注音确认页面继续修改。",
      "4. 调整后的注音和时间轴会自动保存在浏览器中，刷新页面后仍可继续编辑。",
      "性能优化",
      "1. 优化了歌词切分逻辑，提高 FA-Kara 对齐与逐字变色精度。",
      "2. 优化了云端渲染效果。",
      "问题修复",
      "1. 优化“提交内容未通过校验”提示，现在会显示更容易理解的错误原因和修改建议。",
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
