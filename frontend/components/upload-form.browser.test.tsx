// @vitest-environment jsdom

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/mobile-processing", () => ({
  detectMobileCapabilities: vi.fn().mockResolvedValue({}),
  selectMobileProcessingRoute: vi.fn().mockReturnValue("REMOTE_VIDEO"),
}));

vi.mock("@/lib/lyrics-width-validation", () => ({
  detectLyricsWidthOverflow: vi.fn().mockReturnValue({
    availableWidthPx: 1152,
    fullwidthCharacterLimit: 20,
    totalOverflowingLines: 1,
    lines: [{
      lineNumber: 1,
      text: "長い歌詞",
      excerpt: "長い歌詞",
      characterCount: 21,
      widthPx: 1200,
    }],
  }),
  readLyricsValidationSource: vi.fn(async (text: string, file: File | null) => ({
    label: file?.name ?? "粘贴的歌词",
    text: file ? await file.text() : text,
    signature: `lyrics:${file?.name ?? text}`,
  })),
}));

import { UploadForm } from "./upload-form";

describe("UploadForm lyric width timing", () => {
  beforeEach(() => {
    vi.stubGlobal("HTMLDialogElement", window.HTMLDialogElement);
    window.HTMLDialogElement.prototype.showModal = vi.fn();
    window.HTMLDialogElement.prototype.close = vi.fn();
  });

  it("waits until Next is clicked before warning about long pasted lyrics", async () => {
    const { container } = render(<UploadForm />);
    const textarea = screen.getByRole("textbox");

    await act(async () => {
      fireEvent.input(textarea, {
        target: { value: "長い歌詞" },
        inputType: "insertFromPaste",
      });
      fireEvent.blur(textarea);
      await Promise.resolve();
    });

    expect(screen.queryByText("歌词单行可能超出字幕画面")).toBeNull();

    const videoInput = container.querySelector<HTMLInputElement>(
      'input[type="file"][accept*=".mp4"]',
    );
    expect(videoInput).not.toBeNull();
    fireEvent.change(videoInput!, {
      target: { files: [new File(["video"], "song.mp4", { type: "video/mp4" })] },
    });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => {
      expect(screen.getByText("歌词单行可能超出字幕画面")).toBeTruthy();
    });
  });
});
