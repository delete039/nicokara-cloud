// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { JobStatus } from "./job-status";
import { getJob } from "@/services/api";

vi.mock("@/services/api", async (original) => ({
  ...await original<typeof import("@/services/api")>(), getJob: vi.fn(),
}));
vi.mock("./kirakara-preview", () => ({ KirakaraPreview: () => null }));
afterEach(cleanup);

it("removes the duplicate generated video and downloads from the task header", async () => {
  vi.mocked(getJob).mockResolvedValue({
    id: "job-1", status: "COMPLETED", stage: "VIDEO_RENDERING_COMPLETE", progress: 100,
    original_video_name: "song.mp4", video_size_bytes: 5, video_sha256: "test",
    lyrics_source: "text", input_mode: "AUDIO_ONLY", has_timeline: true,
    render_pending: false, render_vocal_mode: "off", available_vocal_modes: ["on", "off"],
    error_code: null, error_message: null, created_at: "2026-09-16", updated_at: "2026-09-16",
  });
  const { container } = render(<JobStatus jobId="job-1" />);
  await screen.findByRole("heading", { name: "ニコカラ视频已生成" });
  expect(screen.queryByRole("heading", { name: "生成结果" })).toBeNull();
  expect(container.querySelector("video")).toBeNull();
  expect(screen.queryByRole("link", { name: "下载 ON VOCAL 视频" })).toBeNull();
  expect(screen.queryByRole("link", { name: "下载 OFF VOCAL 视频" })).toBeNull();
});
