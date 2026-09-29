"use client";

import { Download, LoaderCircle } from "lucide-react";
import { useState } from "react";

import {
  buildKirakaraProject,
  kirakaraProjectFileName,
} from "@/lib/kirakara-project";
import {
  DEFAULT_KIRAKARA_STYLE,
  type KirakaraStyle,
} from "@/lib/kirakara-style";
import {
  toKirakaraTimeline,
  type KirakaraTimeline,
} from "@/lib/kirakara-timeline";
import { JOB_COPY } from "@/lib/ui-copy";
import { getTimeline } from "@/services/api";

export function KirakaraProjectDownload({
  jobId,
  videoName,
  timeline,
  style = DEFAULT_KIRAKARA_STYLE,
  includeRomaji: controlledIncludeRomaji,
}: {
  jobId: string;
  videoName: string;
  timeline?: KirakaraTimeline;
  style?: KirakaraStyle;
  includeRomaji?: boolean;
}) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [localIncludeRomaji, setLocalIncludeRomaji] = useState(false);
  const includeRomaji = controlledIncludeRomaji ?? localIncludeRomaji;

  async function download() {
    if (downloading) return;
    setDownloading(true);
    setError(null);
    try {
      const source = timeline ?? toKirakaraTimeline(await getTimeline(jobId));
      const blob = new Blob([buildKirakaraProject(source, style, { includeRomaji })], {
        type: "text/plain;charset=utf-8",
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = kirakaraProjectFileName(videoName);
      document.body.appendChild(anchor);
      anchor.click();
      globalThis.setTimeout(() => {
        anchor.remove();
        URL.revokeObjectURL(url);
      }, 1000);
    } catch {
      setError("KRL 工程生成失败，请刷新任务页后重试。");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div data-kirakara-project-download="true">
      <button
        type="button"
        onClick={download}
        disabled={downloading}
        className="focus-ring inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground disabled:opacity-60"
      >
        {downloading ? (
          <LoaderCircle className="size-4 animate-spin" />
        ) : (
          <Download className="size-4" />
        )}
        {JOB_COPY.downloadSubtitle}
      </button>
      {controlledIncludeRomaji === undefined && (
        <label className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={localIncludeRomaji}
            onChange={(event) => setLocalIncludeRomaji(event.target.checked)}
          />
          双注音（假名 + 罗马音）
        </label>
      )}
      {error && <p className="mt-2 text-xs text-destructive" role="alert">{error}</p>}
    </div>
  );
}
