"use client";

import { ArrowLeft, LoaderCircle } from "lucide-react";
import { useState } from "react";

export function BackStepButton({
  onBack,
  label = "返回上一步",
  className = "",
}: {
  onBack: () => void | Promise<void>;
  label?: string;
  className?: string;
}) {
  const [pending, setPending] = useState(false);

  async function handleBack() {
    if (pending) return;
    setPending(true);
    try {
      await onBack();
    } finally {
      setPending(false);
    }
  }

  return (
    <button
      type="button"
      onClick={() => void handleBack()}
      disabled={pending}
      className={`focus-ring inline-flex min-h-10 items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-sm font-semibold transition hover:bg-muted disabled:cursor-wait disabled:opacity-60 ${className}`}
    >
      {pending ? <LoaderCircle className="size-4 animate-spin" /> : <ArrowLeft className="size-4" />}
      {pending ? "正在保存并返回…" : label}
    </button>
  );
}
