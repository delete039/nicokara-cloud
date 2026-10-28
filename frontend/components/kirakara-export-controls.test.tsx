import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import {
  KirakaraExportControls,
  resolveExportAudio,
} from "./kirakara-export-controls";

describe("KirakaraExportControls", () => {
  it("offers a local video export command", () => {
    const html = renderToStaticMarkup(
      <KirakaraExportControls
        video={new File(["video"], "song.mp4", { type: "video/mp4" })}
        timeline={{
          confidence: 1,
          warnings: [],
          durationMs: 1000,
          lines: [],
        }}
        profile={{
          codec: "avc1.42E01E",
          width: 1280,
          height: 720,
          framerate: 30,
          bitrate: 4_000_000,
        }}
      />,
    );

    expect(html).toContain("导出本地视频");
    expect(html).toContain("这是串联导出的第一步");
  });

  it("switches the local command to audio replacement when the other version is ready", () => {
    const html = renderToStaticMarkup(
      <KirakaraExportControls
        video={new File(["video"], "song.mp4", { type: "video/mp4" })}
        counterpartVideo={new File(["rendered"], "song.on-vocal.nicokara.mp4")}
        timeline={{ confidence: 1, warnings: [], durationMs: 1000, lines: [] }}
        profile={{
          codec: "avc1.42E01E",
          width: 1280,
          height: 720,
          framerate: 30,
          bitrate: 4_000_000,
        }}
        vocalMode="off"
      />,
    );

    expect(html).toContain("替换音轨导出");
    expect(html).toContain("复用已生成的视频画面");
  });

  it("explains that a ready separated instrumental is reused", () => {
    const html = renderToStaticMarkup(
      <KirakaraExportControls
        video={new File(["video"], "song.mp4", { type: "video/mp4" })}
        instrumentalReady
        vocalMode="off"
        timeline={{ confidence: 1, warnings: [], durationMs: 1000, lines: [] }}
        profile={{
          codec: "avc1.42E01E",
          width: 1280,
          height: 720,
          framerate: 30,
          bitrate: 4_000_000,
        }}
      />,
    );

    expect(html).toContain("不会重复分离");
  });
});

describe("resolveExportAudio", () => {
  it("downloads a replacement track only for off-vocal jobs", async () => {
    const instrumental = new File(["audio"], "instrumental.wav");
    const loader = async () => instrumental;

    await expect(resolveExportAudio("job-1", "off", loader)).resolves.toBe(
      instrumental,
    );
    await expect(resolveExportAudio("job-1", "on", loader)).resolves.toBeUndefined();
  });

  it("downloads the already separated instrumental directly when it is ready", async () => {
    const instrumental = new File(["audio"], "instrumental.wav");
    const prepare = vi.fn(async () => {
      throw new Error("should not prepare again");
    });
    const download = vi.fn(async () => instrumental);

    await expect(
      resolveExportAudio("job-1", "off", prepare, undefined, true, download),
    ).resolves.toBe(instrumental);
    expect(download).toHaveBeenCalledWith("job-1", undefined);
    expect(prepare).not.toHaveBeenCalled();
  });
});
