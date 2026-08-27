"use client";

import { ArrowLeft, LoaderCircle } from "lucide-react";

export function ReadingRevisionControls({
  reopening,
  onReopen,
}: {
  reopening: boolean;
  onReopen: () => void;
}) {
  return (
    <section className="mt-6 border-l-2 border-primary pl-4">
      <p className="text-sm leading-6 text-muted-foreground">
        可以以上次保存的注音为基础继续修改。保存后将重新生成时间轴、字幕和视频。
      </p>
      <button
        type="button"
        disabled={reopening}
        onClick={onReopen}
        className="focus-ring mt-3 inline-flex min-h-11 items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-sm font-semibold transition hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
      >
        {reopening ? (
          <LoaderCircle className="size-4 animate-spin" />
        ) : (
          <ArrowLeft className="size-4" />
        )}
        {reopening ? "正在返回" : "上一步：修改假名注音"}
      </button>
    </section>
  );
}
