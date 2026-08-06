import { describe, expect, it, vi } from "vitest";

import { createBrowserFileDestination } from "./browser-file-destination";

describe("createBrowserFileDestination", () => {
  it("returns null when the browser cannot stream directly to a file", async () => {
    await expect(
      createBrowserFileDestination("song.mp4", {}),
    ).resolves.toBeNull();
  });

  it("wraps a selected file handle as a sequential byte stream", async () => {
    const sink = {
      write: vi.fn().mockResolvedValue(undefined),
      close: vi.fn().mockResolvedValue(undefined),
      abort: vi.fn().mockResolvedValue(undefined),
    };
    const showSaveFilePicker = vi.fn().mockResolvedValue({
      createWritable: vi.fn().mockResolvedValue(sink),
    });

    const destination = await createBrowserFileDestination("song.mp4", {
      showSaveFilePicker,
    });
    const writer = destination?.getWriter();
    await writer?.write(new Uint8Array([1, 2, 3]));
    await writer?.close();

    expect(showSaveFilePicker).toHaveBeenCalledWith(
      expect.objectContaining({ suggestedName: "song.mp4" }),
    );
    expect(sink.write).toHaveBeenCalledWith(new Uint8Array([1, 2, 3]));
    expect(sink.close).toHaveBeenCalledOnce();
  });
});
