"use client";

import { AlertTriangle, X } from "lucide-react";
import { useEffect, useRef } from "react";

import type { LyricsWidthOverflowReport } from "@/lib/lyrics-width-validation";

type LyricsOverflowDialogProps = {
  report: LyricsWidthOverflowReport;
  sourceLabel: string;
  onCancel: () => void;
  onContinue: () => void;
};

export function LyricsOverflowDialog({
  report,
  sourceLabel,
  onCancel,
  onContinue,
}: LyricsOverflowDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    if (!dialog.open) dialog.showModal();

    return () => {
      document.body.style.overflow = previousOverflow;
      if (dialog.open) dialog.close();
    };
  }, []);

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="lyrics-overflow-title"
      aria-describedby="lyrics-overflow-description"
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
      className="m-auto max-h-[calc(100dvh-2rem)] w-[min(38rem,calc(100vw-2rem))] overflow-hidden rounded-lg border border-amber-300 bg-card p-0 text-card-foreground shadow-2xl backdrop:bg-foreground/55 backdrop:backdrop-blur-[2px]"
    >
      <div className="flex items-start justify-between gap-4 border-b border-amber-200 px-5 py-4 sm:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-amber-100 text-amber-700">
            <AlertTriangle className="size-4" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{sourceLabel}</p>
            <h2 id="lyrics-overflow-title" className="text-lg font-semibold">
              歌词单行可能超出字幕画面
            </h2>
          </div>
        </div>
        <button
          type="button"
          onClick={onCancel}
          aria-label="关闭歌词长度提醒"
          title="关闭"
          className="focus-ring flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </div>

      <div
        id="lyrics-overflow-description"
        className="max-h-[min(58dvh,31rem)] overflow-y-auto px-5 py-5 text-sm leading-6 sm:px-6"
      >
        <p>
          按 Kirakara 最小字号 48 px 和当前横屏画布计算，单行上限约{" "}
          {report.fullwidthCharacterLimit} 个全角字符；汉字注音较宽时会进一步占用空间。
          以下歌词在生成后可能被裁切或挤出画面。
        </p>
        <p className="mt-2 font-semibold">确认要继续吗？</p>

        <ul className="mt-4 divide-y rounded-lg border">
          {report.lines.map((line) => (
            <li key={line.lineNumber} className="px-3 py-2.5">
              <div className="flex flex-wrap justify-between gap-x-3 text-xs text-muted-foreground">
                <span>第 {line.lineNumber} 行</span>
                <span>
                  {line.characterCount} 字符 · 约 {line.widthPx} px / {report.availableWidthPx} px
                </span>
              </div>
              <p className="mt-1 break-all text-foreground">{line.excerpt}</p>
            </li>
          ))}
        </ul>
        {report.totalOverflowingLines > report.lines.length && (
          <p className="mt-2 text-xs text-muted-foreground">
            另有 {report.totalOverflowingLines - report.lines.length} 行存在相同风险。
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-2 border-t bg-muted/45 px-5 py-4 sm:grid-cols-2 sm:px-6">
        <button
          type="button"
          onClick={onCancel}
          autoFocus
          className="focus-ring inline-flex items-center justify-center rounded-lg border bg-background px-4 py-2.5 text-sm font-semibold transition hover:bg-muted"
        >
          返回修改
        </button>
        <button
          type="button"
          onClick={onContinue}
          className="focus-ring inline-flex items-center justify-center rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground transition hover:brightness-95"
        >
          忽略风险并继续
        </button>
      </div>
    </dialog>
  );
}
