/* @vitest-environment jsdom */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ANNOUNCEMENT_OPEN_EVENT } from "@/lib/announcement";

import { AnnouncementDialog, isAnnouncementHeadline } from "./announcement-dialog";

describe("announcement headline styling", () => {
  it("recognizes the major update headline", () => {
    expect(isAnnouncementHeadline("！！！！！重大更新！！！！！")).toBe(true);
    expect(isAnnouncementHeadline("更新内容：")).toBe(false);
  });
});

describe("announcement history", () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
      configurable: true,
      value() {
        this.open = true;
      },
    });
    Object.defineProperty(HTMLDialogElement.prototype, "close", {
      configurable: true,
      value() {
        this.open = false;
      },
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      id: "current",
      enabled: true,
      title: "当前公告",
      content: ["当前内容"],
      history: [{
        id: "older",
        title: "旧公告",
        publishedAt: "2026-08-01",
        content: ["旧内容"],
      }],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));
  });

  it("shows history from both the automatic popup and the announcement action", async () => {
    render(<AnnouncementDialog />);
    await screen.findByRole("heading", { name: "当前公告" });

    fireEvent.click(screen.getByRole("button", { name: "查看历史公告" }));
    expect(screen.getByRole("heading", { name: "历史公告" })).toBeTruthy();
    expect(screen.getByText("旧公告")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "返回当前公告" }));
    expect(screen.getByRole("heading", { name: "当前公告" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "关闭公告" }));
    fireEvent(window, new Event(ANNOUNCEMENT_OPEN_EVENT));
    await waitFor(() => expect(screen.getByRole("heading", { name: "当前公告" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "查看历史公告" }));
    fireEvent.click(screen.getByRole("button", { name: /旧公告/ }));
    expect(screen.getByText("旧内容")).toBeTruthy();
  });
});
