"use client";

import { Check, LoaderCircle } from "lucide-react";

import type { ProcessedLyrics } from "@/types/job";

export function ReadingReviewEditor({
  lyrics,
  submitting,
  onChange,
  onConfirm,
}: {
  lyrics: ProcessedLyrics;
  submitting: boolean;
  onChange: (lyrics: ProcessedLyrics) => void;
  onConfirm: () => void;
}) {
  const valid = lyrics.lines.length > 0 && lyrics.lines.every(
    (line) => line.tokens.length > 0 && line.tokens.every(
      (token) => token.reading.trim().length > 0,
    ),
  );

  function updateReading(
    lineIndex: number,
    tokenIndex: number,
    reading: string,
  ) {
    const lines = lyrics.lines.map((line, candidateLineIndex) => {
      if (candidateLineIndex !== lineIndex) return line;
      const tokens = line.tokens.map((token, candidateTokenIndex) =>
        candidateTokenIndex === tokenIndex
          ? { ...token, reading }
          : token,
      );
      return {
        ...line,
        reading: tokens.map((token) => token.reading).join(""),
        tokens,
      };
    });
    onChange({ ...lyrics, lines });
  }

  return (
    <section className="mt-6 border-t pt-6" aria-labelledby="reading-review-heading">
      <h2 id="reading-review-heading" className="text-xl font-bold">
        确认假名注音
      </h2>
      <div className="mt-4 max-h-[34rem] divide-y overflow-y-auto overscroll-contain border-y [scrollbar-gutter:stable]">
        {lyrics.lines.map((line, lineIndex) => (
          <section key={`${lineIndex}-${line.surface}`} className="py-4">
            <h3 className="break-all text-sm font-bold">
              {lineIndex + 1}. {line.surface}
            </h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {line.tokens.map((token, tokenIndex) => (
                <label
                  key={`${tokenIndex}-${token.surface}`}
                  className="min-w-0 text-xs font-medium text-muted-foreground"
                >
                  <span className="block break-all text-sm font-semibold text-foreground">
                    {token.surface}
                  </span>
                  <span className="sr-only">假名读音</span>
                  <input
                    type="text"
                    value={token.reading}
                    disabled={submitting}
                    onChange={(event) => updateReading(
                      lineIndex,
                      tokenIndex,
                      event.target.value,
                    )}
                    className="focus-ring mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm text-foreground disabled:opacity-60"
                  />
                </label>
              ))}
            </div>
          </section>
        ))}
      </div>
      <button
        type="button"
        disabled={!valid || submitting}
        onClick={onConfirm}
        className="focus-ring mt-5 inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-60"
      >
        {submitting ? (
          <LoaderCircle className="size-4 animate-spin" />
        ) : (
          <Check className="size-4" />
        )}
        {submitting ? "正在保存" : "保存注音并开始对齐"}
      </button>
    </section>
  );
}
