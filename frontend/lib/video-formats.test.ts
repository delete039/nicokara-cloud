import { describe, expect, it } from "vitest";

import {
  isSupportedVideoName,
  SUPPORTED_VIDEO_ACCEPT,
  SUPPORTED_VIDEO_EXTENSIONS,
} from "./video-formats";

describe("video format compatibility", () => {
  it("accepts the common container extensions case-insensitively", () => {
    for (const extension of SUPPORTED_VIDEO_EXTENSIONS) {
      expect(isSupportedVideoName(`sample${extension.toUpperCase()}`)).toBe(true);
    }
  });

  it("rejects audio, subtitle, and unknown extensions", () => {
    for (const name of ["track.mp3", "captions.srt", "video.xyz", "video"]) {
      expect(isSupportedVideoName(name)).toBe(false);
    }
  });

  it("keeps both MIME types and extensions in the file picker filter", () => {
    expect(SUPPORTED_VIDEO_ACCEPT).toContain("video/mp4");
    expect(SUPPORTED_VIDEO_ACCEPT).toContain("video/x-matroska");
    expect(SUPPORTED_VIDEO_ACCEPT).toContain(".mov");
    expect(SUPPORTED_VIDEO_ACCEPT).toContain(".m2ts");
  });
});
