import { AlertTriangle, PencilLine, RefreshCw } from "lucide-react";

import type { ErrorFeedback } from "@/lib/error-feedback";

type ErrorFeedbackPanelProps = {
  feedback: ErrorFeedback;
  onRetry?: () => void;
  retryLabel?: string;
  retrying?: boolean;
  onEdit?: () => void;
};

export function ErrorFeedbackPanel({
  feedback,
  onRetry,
  retryLabel,
  retrying = false,
  onEdit,
}: ErrorFeedbackPanelProps) {
  return (
    <section
      role="alert"
      aria-labelledby="error-feedback-title"
      className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-left sm:p-5"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" />
        <div className="min-w-0 flex-1">
          <h3
            id="error-feedback-title"
            className="text-base font-semibold text-destructive"
          >
            {feedback.title}
          </h3>
          <p className="mt-1.5 text-sm leading-6 text-foreground">
            {feedback.description}
          </p>

          <div className="mt-4">
            <p className="text-sm font-semibold">建议处理</p>
            <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-sm leading-6 text-muted-foreground">
              {feedback.solutions.map((solution) => (
                <li key={solution}>{solution}</li>
              ))}
            </ol>
          </div>

          {feedback.technicalDetails.length > 0 && (
            <details className="mt-4 border-t border-destructive/15 pt-3">
              <summary className="focus-ring w-fit cursor-pointer rounded-sm text-xs font-medium text-muted-foreground">
                技术信息
              </summary>
              <ul className="mt-2 space-y-1 font-mono text-xs leading-5 text-muted-foreground">
                {feedback.technicalDetails.map((detail) => (
                  <li key={detail} className="break-words">
                    {detail}
                  </li>
                ))}
              </ul>
            </details>
          )}

          {onRetry && (feedback.retryable || retryLabel) && (
            <button
              type="button"
              onClick={onRetry}
              disabled={retrying}
              className="focus-ring mt-4 inline-flex items-center gap-2 rounded-lg border border-destructive/25 bg-card px-3 py-2 text-sm font-semibold text-foreground transition hover:bg-muted disabled:cursor-wait disabled:opacity-60"
            >
              <RefreshCw className={`size-4 ${retrying ? "animate-spin" : ""}`} />
              {retrying ? "正在重新加入队列…" : retryLabel ?? "重新检查"}
            </button>
          )}
          {onEdit && (
            <button
              type="button"
              onClick={onEdit}
              className="focus-ring mt-4 inline-flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm font-semibold text-foreground transition hover:bg-muted"
            >
              <PencilLine className="size-4" />
              返回修改
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
