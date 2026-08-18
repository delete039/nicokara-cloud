"use client";

import { Megaphone, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ANNOUNCEMENT_CONFIG_URL,
  ANNOUNCEMENT_OPEN_EVENT,
  hasSeenAnnouncement,
  markAnnouncementSeen,
  parseAnnouncement,
} from "@/lib/announcement";
import type { Announcement } from "@/types/announcement";

export function AnnouncementDialog() {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [announcement, setAnnouncement] = useState<Announcement | null>(null);
  const [openRequested, setOpenRequested] = useState(false);

  useEffect(() => {
    const controller = new AbortController();

    async function loadAnnouncement() {
      try {
        const response = await fetch(ANNOUNCEMENT_CONFIG_URL, {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) return;
        const parsed = parseAnnouncement(await response.json());
        if (!parsed) return;

        let seen = false;
        try {
          seen = hasSeenAnnouncement(window.localStorage, parsed.id);
        } catch {
          // Storage can be unavailable in strict privacy modes; still show it.
        }
        setAnnouncement(parsed);
        if (!seen) setOpenRequested(true);
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
      }
    }

    void loadAnnouncement();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const handleOpen = () => setOpenRequested(true);
    window.addEventListener(ANNOUNCEMENT_OPEN_EVENT, handleOpen);
    return () => window.removeEventListener(ANNOUNCEMENT_OPEN_EVENT, handleOpen);
  }, []);

  useEffect(() => {
    if (!announcement || !openRequested) return;
    const dialog = dialogRef.current;
    if (!dialog) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    if (!dialog.open) dialog.showModal();

    return () => {
      document.body.style.overflow = previousOverflow;
      if (dialog.open) dialog.close();
    };
  }, [announcement, openRequested]);

  const dismiss = useCallback(() => {
    if (!announcement) return;
    try {
      markAnnouncementSeen(window.localStorage, announcement.id);
    } catch {
      // Closing the announcement should not depend on storage availability.
    }
    dialogRef.current?.close();
    setOpenRequested(false);
  }, [announcement]);

  if (!announcement) return null;

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="announcement-title"
      aria-describedby="announcement-content"
      onCancel={(event) => {
        event.preventDefault();
        dismiss();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) dismiss();
      }}
      className="m-auto max-h-[calc(100dvh-2rem)] w-[min(34rem,calc(100vw-2rem))] overflow-hidden rounded-lg border bg-card p-0 text-card-foreground shadow-2xl backdrop:bg-foreground/55 backdrop:backdrop-blur-[2px]"
    >
      <div className="flex items-start justify-between gap-4 border-b px-5 py-4 sm:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent text-primary">
            <Megaphone className="size-4" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h2 id="announcement-title" className="text-lg font-semibold">
              {announcement.title}
            </h2>
            {announcement.publishedAt && (
              <p className="mt-0.5 text-xs text-muted-foreground">
                {announcement.publishedAt}
              </p>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={dismiss}
          aria-label="关闭公告"
          title="关闭公告"
          className="focus-ring flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-foreground"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </div>

      <div
        id="announcement-content"
        className="max-h-[min(55dvh,28rem)] space-y-4 overflow-y-auto px-5 py-5 text-sm leading-7 sm:px-6"
      >
        {announcement.content.map((paragraph, index) => (
          <p key={`${announcement.id}-${index}`}>{paragraph}</p>
        ))}
      </div>

      <div className="border-t bg-muted/45 px-5 py-4 sm:px-6">
        <button
          type="button"
          onClick={dismiss}
          autoFocus
          className="focus-ring inline-flex w-full items-center justify-center rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground transition hover:brightness-95"
        >
          {announcement.buttonLabel}
        </button>
      </div>
    </dialog>
  );
}
