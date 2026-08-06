import { beforeEach, describe, expect, it } from "vitest";

import {
  clearLocalMediaSessions,
  forgetLocalVideo,
  getLocalVideo,
  rememberLocalVideo,
} from "./local-media-session";

describe("local media session", () => {
  beforeEach(clearLocalMediaSessions);

  it("keeps the original browser File available on the job page", () => {
    const video = new File(["video"], "song.mp4", { type: "video/mp4" });

    rememberLocalVideo("job-1", video);

    expect(getLocalVideo("job-1")).toBe(video);
  });

  it("forgets only the requested job video", () => {
    rememberLocalVideo("job-1", new File(["1"], "one.mp4"));
    rememberLocalVideo("job-2", new File(["2"], "two.mp4"));

    forgetLocalVideo("job-1");

    expect(getLocalVideo("job-1")).toBeNull();
    expect(getLocalVideo("job-2")?.name).toBe("two.mp4");
  });
});
