import { describe, expect, it, vi } from "vitest";

import { createBrowserFileDestination } from "./browser-file-destination";

describe("createBrowserFileDestination", () => {
  it("returns null when the browser cannot stream directly to a file", async () => {
    await expect(
      createBrowserFileDestination("song.mp4", {}),
    ).resolves.toBeNull();
  });

  it("wraps a selected file handle as a random-access media stream", async () => {
    const savedFile = new File(["saved"], "song.mp4", { type: "video/mp4" });
    const sink = {
      write: vi.fn().mockResolvedValue(undefined),
      close: vi.fn().mockResolvedValue(undefined),
      abort: vi.fn().mockResolvedValue(undefined),
    };
    const getFile = vi.fn().mockResolvedValue(savedFile);
    const showSaveFilePicker = vi.fn().mockResolvedValue({
      createWritable: vi.fn().mockResolvedValue(sink),
      getFile,
    });

    const destination = await createBrowserFileDestination("song.mp4", {
      showSaveFilePicker,
    });
    const writer = destination?.writable.getWriter();
    const chunk = {
      type: "write" as const,
      data: new Uint8Array([1, 2, 3]),
      position: 64,
    };
    await writer?.write(chunk);
    await writer?.close();

    expect(showSaveFilePicker).toHaveBeenCalledWith(
      expect.objectContaining({ suggestedName: "song.mp4" }),
    );
    expect(sink.write).toHaveBeenCalledWith(chunk);
    expect(sink.close).toHaveBeenCalledOnce();
    await expect(destination?.getFile()).resolves.toBe(savedFile);
    expect(getFile).toHaveBeenCalledOnce();
  });
});
