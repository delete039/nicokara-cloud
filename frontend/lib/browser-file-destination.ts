type BrowserFileSink = {
  write(data: Uint8Array): Promise<void>;
  close(): Promise<void>;
  abort(reason?: unknown): Promise<void>;
};

type BrowserFileHandle = {
  createWritable(): Promise<BrowserFileSink>;
};

type FilePickerScope = {
  showSaveFilePicker?: (options: {
    suggestedName: string;
    types: Array<{
      description: string;
      accept: Record<string, string[]>;
    }>;
  }) => Promise<BrowserFileHandle>;
};

export async function createBrowserFileDestination(
  fileName: string,
  scope: FilePickerScope = globalThis as FilePickerScope,
): Promise<WritableStream<Uint8Array> | null> {
  if (!scope.showSaveFilePicker) return null;
  const handle = await scope.showSaveFilePicker({
    suggestedName: fileName,
    types: [
      {
        description: "MP4 视频",
        accept: { "video/mp4": [".mp4"] },
      },
    ],
  });
  const sink = await handle.createWritable();
  return new WritableStream<Uint8Array>({
    write(chunk) {
      return sink.write(chunk);
    },
    close() {
      return sink.close();
    },
    abort(reason) {
      return sink.abort(reason);
    },
  });
}
