import type { StreamTargetChunk } from "mediabunny";

type BrowserFileSink = {
  write(chunk: StreamTargetChunk): Promise<void>;
  close(): Promise<void>;
  abort(reason?: unknown): Promise<void>;
};

type BrowserFileHandle = {
  createWritable(): Promise<BrowserFileSink>;
  getFile(): Promise<File>;
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

export type BrowserFileDestination = {
  writable: WritableStream<StreamTargetChunk>;
  getFile(): Promise<File>;
};

export async function createBrowserFileDestination(
  fileName: string,
  scope: FilePickerScope = globalThis as FilePickerScope,
): Promise<BrowserFileDestination | null> {
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
  return {
    writable: new WritableStream<StreamTargetChunk>({
      write(chunk) {
        return sink.write(chunk);
      },
      close() {
        return sink.close();
      },
      abort(reason) {
        return sink.abort(reason);
      },
    }),
    getFile() {
      return handle.getFile();
    },
  };
}
