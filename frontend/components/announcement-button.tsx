"use client";

import { Megaphone } from "lucide-react";

import { ANNOUNCEMENT_OPEN_EVENT } from "@/lib/announcement";

export function AnnouncementButton() {
  return (
    <button
      type="button"
      onClick={() => window.dispatchEvent(new Event(ANNOUNCEMENT_OPEN_EVENT))}
      className="focus-ring inline-flex min-h-10 items-center gap-2 rounded-lg border bg-card px-4 py-2 text-sm font-semibold transition hover:bg-muted"
    >
      <Megaphone className="size-4" aria-hidden="true" />
      打开公告
    </button>
  );
}
