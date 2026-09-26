"use client";

import { Cloud, Film, FolderOpen, LoaderCircle, RefreshCw, Settings2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { KirakaraCanvasFrame } from "@/components/kirakara-canvas-frame";
import { KirakaraRenderActions } from "@/components/kirakara-render-actions";
import { KirakaraReviewEditor } from "@/components/kirakara-review-editor";
import { KirakaraStyleEditor } from "@/components/kirakara-style-editor";
import { ReviewedDataDownloads } from "@/components/reviewed-data-downloads";
import {
  detectKirakaraCapabilities,
  kirakaraSupportMessage,
  type KirakaraCapabilities,
} from "@/lib/kirakara-capabilities";
import {
  DEFAULT_KIRAKARA_STYLE,
  loadKirakaraStyle,
  saveKirakaraStyle,
  type KirakaraStyle,
} from "@/lib/kirakara-style";
import {
  activeKirakaraFrame,
  toKirakaraTimeline,
  type KirakaraFrame,
  type KirakaraTimeline,
} from "@/lib/kirakara-timeline";
import {
  TimelineReviewValidationError,
  timelineReviewPayload,
} from "@/lib/kirakara-review";
import { getLocalVideo, rememberLocalVideo } from "@/lib/local-media-session";
import {
  compatibleTimelineDraft,
  loadBrowserReviewDraft,
  saveBrowserReviewDraft,
} from "@/lib/review-draft-store";
import {
  ApiRequestError,
  getTimeline,
  getTimelineReviewDraft,
  saveTimelineReviewDraft,
} from "@/services/api";
import type { Job } from "@/types/job";
import {
  activeTimelineLineIndex, createTimelineHistory, DEFAULT_PLAYBACK_SHORTCUT_BINDINGS, formatPlaybackSeconds,
  loopPlaybackTime, playbackShortcut, PLAYBACK_RATES, PLAYBACK_SEEK_STEP_MS, PlaybackShortcut,
  previewSeekMs, recordTimelineEdit, redoTimelineEdit, stepPlaybackRate,
  undoTimelineEdit, type PlaybackRange, type PlaybackShortcutBindings, type TimelineHistory,
} from "@/lib/timeline-editing";
import {
  DEFAULT_PREVIEW_LEAD_MS,
  loadPlaybackShortcutBindings,
  loadPreviewLeadMs,
  normalizePlaybackShortcutKey,
  savePlaybackShortcutBindings,
  savePreviewLeadMs,
} from "@/lib/playback-preferences";

const TIMELINE_AUTOSAVE_DELAY_MS = 600;
export const RATE_NOTICE_DURATION_MS = 1000;

type TimelineSaveState = {
  phase: "idle" | "pending" | "saving" | "saved" | "restored" | "error";
  message?: string;
  refreshRequired?: boolean;
};

enum WorkbenchSideTab {
  Lyrics = "lyrics",
  Style = "style",
}

const QUICK_LINE_SHORTCUT_SETTINGS = [
  { shortcut: PlaybackShortcut.PreviousLine, label: "上一句" },
  { shortcut: PlaybackShortcut.NextLine, label: "下一句" },
  { shortcut: PlaybackShortcut.ReplayLine, label: "本句重播" },
  { shortcut: PlaybackShortcut.ToggleLineLoop, label: "本句循环" },
] as const;

const MORA_SHORTCUT_SETTINGS = [
  { shortcut: PlaybackShortcut.PreviousMora, label: "上一个 Mora" },
  { shortcut: PlaybackShortcut.NextMora, label: "下一个 Mora" },
] as const;

const PLAYBACK_RATE_SHORTCUT_SETTINGS = [
  { shortcut: PlaybackShortcut.RateToggle, label: "切换常速" },
  { shortcut: PlaybackShortcut.RateDown, label: "降低倍速" },
  { shortcut: PlaybackShortcut.RateUp, label: "提高倍速" },
] as const;

export function scrollLyricWithinNavigator(
  navigator: Pick<HTMLElement, "getBoundingClientRect" | "scrollTop">,
  item: Pick<HTMLElement, "getBoundingClientRect">,
) {
  const navigatorRect = navigator.getBoundingClientRect();
  const itemRect = item.getBoundingClientRect();
  if (itemRect.top < navigatorRect.top) {
    navigator.scrollTop = Math.max(0, navigator.scrollTop - (navigatorRect.top - itemRect.top));
  } else if (itemRect.bottom > navigatorRect.bottom) {
    navigator.scrollTop += itemRect.bottom - navigatorRect.bottom;
  }
}

function KirakaraLyricNavigator({
  timeline,
  playbackLineIndex,
  editingLineIndex,
  onSelect,
}: {
  timeline: KirakaraTimeline;
  playbackLineIndex: number | null;
  editingLineIndex: number | null;
  onSelect: (index: number) => void;
}) {
  const navigatorRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    if (playbackLineIndex === null) return;
    const navigator = navigatorRef.current;
    const item = itemRefs.current[playbackLineIndex];
    if (navigator && item) scrollLyricWithinNavigator(navigator, item);
  }, [playbackLineIndex]);

  return (
    <div
      ref={navigatorRef}
      data-lyric-navigator="true"
      className="max-h-[min(32rem,55vh)] overflow-y-auto rounded-md border [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      {timeline.lines.map((line, index) => {
        const playing = playbackLineIndex === index;
        const editing = editingLineIndex === index;
        return (
          <button
            key={index}
            ref={(element) => { itemRefs.current[index] = element; }}
            type="button"
            data-lyric-line={index}
            data-editing-line={editing ? "true" : undefined}
            aria-label={`${index + 1}. ${line.text}`}
            aria-current={playing ? "true" : undefined}
            onClick={() => onSelect(index)}
            className={`focus-ring flex w-full items-start gap-2 border-b px-3 py-2 text-left text-sm last:border-b-0 ${
              playing ? "bg-primary/10 text-primary" : "hover:bg-muted"
            } ${editing ? "font-semibold ring-1 ring-inset ring-primary" : ""}`}
          >
            <span className="w-7 shrink-0 text-right tabular-nums text-muted-foreground">{index + 1}.</span>
            <span className="min-w-0 flex-1">{line.text}</span>
            {playing && <span className="shrink-0 text-xs" aria-label="当前播放位置">当前</span>}
          </button>
        );
      })}
    </div>
  );
}

type PreviewFrameLoopOptions = {
  draw: () => void;
  isPlaying: () => boolean;
  requestFrame?: (callback: FrameRequestCallback) => number;
  cancelFrame?: (handle: number) => void;
};

export function createPreviewFrameLoop({
  draw: initialDraw,
  isPlaying,
  requestFrame = (callback) => globalThis.requestAnimationFrame(callback),
  cancelFrame = (handle) => globalThis.cancelAnimationFrame(handle),
}: PreviewFrameLoopOptions) {
  let draw = initialDraw;
  let scheduledFrame: number | null = null;
  const stop = () => {
    if (scheduledFrame === null) return;
    cancelFrame(scheduledFrame);
    scheduledFrame = null;
  };
  const tick: FrameRequestCallback = () => {
    scheduledFrame = null;
    draw();
    if (isPlaying()) {
      scheduledFrame = requestFrame(tick);
    }
  };

  return {
    setDraw(nextDraw: () => void) {
      draw = nextDraw;
      draw();
    },
    start() {
      stop();
      tick(0);
    },
    stop,
  };
}

export function playbackRateAfterShortcut(
  shortcut: PlaybackShortcut,
  currentRate: number,
  lastNonDefaultRate: number,
): number {
  if (shortcut === PlaybackShortcut.RateDown) return stepPlaybackRate(currentRate, -1);
  if (shortcut === PlaybackShortcut.RateUp) return stepPlaybackRate(currentRate, 1);
  if (shortcut === PlaybackShortcut.RateToggle) return currentRate === 1 ? lastNonDefaultRate : 1;
  return currentRate;
}

export function seekVideoWithoutPlaybackChange(
  video: Pick<HTMLVideoElement, "currentTime" | "duration">,
  milliseconds: number,
): number {
  const durationMs = Number.isFinite(video.duration) ? video.duration * 1000 : undefined;
  const targetMs = previewSeekMs(milliseconds, 0, durationMs);
  video.currentTime = targetMs / 1000;
  return targetMs;
}

export function PlaybackRateNotice({ rate }: { rate: number | null }) {
  if (rate === null) return null;
  return (
    <div
      data-playback-rate-notice="true"
      aria-live="polite"
      className="pointer-events-none absolute right-3 top-3 rounded bg-black/70 px-2.5 py-1.5 text-sm font-semibold text-white"
    >
      {rate.toFixed(1)}×
    </div>
  );
}

export function KirakaraPreview({
  jobId,
  expectedVideoName,
  hasCloudResult = false,
  exportDisabled = false,
  availableModes = [],
  resultVersion,
  job,
  onCloudRenderQueued = () => undefined,
  onVideoElementChange,
}: {
  jobId: string;
  expectedVideoName: string;
  hasCloudResult?: boolean;
  exportDisabled?: boolean;
  availableModes?: Array<"on" | "off">;
  resultVersion?: string;
  job?: Job;
  onCloudRenderQueued?: (job: Job) => void;
  onVideoElementChange?: (element: HTMLVideoElement | null) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const frameLoop = useRef<ReturnType<typeof createPreviewFrameLoop> | null>(null);
  const componentActive = useRef(true);
  const activeJobId = useRef(jobId);
  const autosaveVersion = useRef(0);
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  const timelineDraftJobId = useRef<string | null>(null);
  const savedAtRef = useRef<string | null>(null);
  const [cloudSavedAt, setCloudSavedAt] = useState<string | null>(null);
  const [video, setVideo] = useState<File | null>(() => getLocalVideo(jobId));
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<KirakaraTimeline | null>(null);
  const history = useRef<TimelineHistory | null>(null);
  const [historyAvailability, setHistoryAvailability] = useState({ canUndo: false, canRedo: false });
  const loopRange = useRef<PlaybackRange | null>(null);
  const [looping, setLooping] = useState(false);
  const [playbackError, setPlaybackError] = useState<string | null>(null);
  const [playbackLineIndex, setPlaybackLineIndex] = useState<number | null>(null);
  const playbackLineIndexRef = useRef<number | null>(null);
  const [editingLineIndex, setEditingLineIndex] = useState<number | null>(null);
  const programmaticSeekLineRef = useRef<number | null>(null);
  const [playbackMs, setPlaybackMs] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [lastNonDefaultRate, setLastNonDefaultRate] = useState(0.9);
  const [rateNotice, setRateNotice] = useState<number | null>(null);
  const [sideTab, setSideTab] = useState(WorkbenchSideTab.Lyrics);
  const rateNoticeTimer = useRef<ReturnType<typeof globalThis.setTimeout> | null>(null);
  const [previewLeadMs, setPreviewLeadMs] = useState(() =>
    typeof window === "undefined"
      ? DEFAULT_PREVIEW_LEAD_MS
      : loadPreviewLeadMs(window.localStorage),
  );
  const [shortcutBindings, setShortcutBindings] = useState<PlaybackShortcutBindings>(() =>
    typeof window === "undefined"
      ? { ...DEFAULT_PLAYBACK_SHORTCUT_BINDINGS }
      : loadPlaybackShortcutBindings(window.localStorage),
  );
  const [shortcutError, setShortcutError] = useState<string | null>(null);
  const [frame, setFrame] = useState<KirakaraFrame | null>(null);
  const [timelineError, setTimelineError] = useState<string | null>(null);
  const [autosaveTrigger, setAutosaveTrigger] = useState<{
    jobId: string;
    version: number;
  } | null>(null);
  const [timelineSaveState, setTimelineSaveState] = useState<TimelineSaveState>({
    phase: "idle",
  });
  const [selectionWarning, setSelectionWarning] = useState<string | null>(null);
  const [capabilities, setCapabilities] =
    useState<KirakaraCapabilities | null>(null);
  const [style, setStyle] = useState<KirakaraStyle>(() =>
    typeof window === "undefined"
      ? DEFAULT_KIRAKARA_STYLE
      : loadKirakaraStyle(window.localStorage),
  );

  const assignVideoElement = useCallback((element: HTMLVideoElement | null) => {
    videoRef.current = element;
    onVideoElementChange?.(element);
  }, [onVideoElementChange]);

  useEffect(() => {
    componentActive.current = true;
    return () => {
      componentActive.current = false;
    };
  }, []);

  useEffect(() => {
    activeJobId.current = jobId;
    autosaveVersion.current = 0;
    timelineDraftJobId.current = null;
    savedAtRef.current = null;
    history.current = null;
    loopRange.current = null;
    playbackLineIndexRef.current = null;
    programmaticSeekLineRef.current = null;
    globalThis.queueMicrotask(() => {
      if (activeJobId.current !== jobId) return;
      setPlaybackLineIndex(null);
      setEditingLineIndex(null);
      setLooping(false);
      setPlaybackMs(0);
      setIsPlaying(false);
    });
  }, [jobId]);

  useEffect(() => () => {
    if (rateNoticeTimer.current !== null) globalThis.clearTimeout(rateNoticeTimer.current);
  }, []);

  useEffect(() => {
    let active = true;
    Promise.allSettled([
      getTimeline(jobId),
      getTimelineReviewDraft(jobId),
      loadBrowserReviewDraft<KirakaraTimeline>(jobId, "timeline"),
    ]).then(([sourceResult, cloudDraftResult, browserDraftResult]) => {
      if (!active) return;
      if (sourceResult.status === "rejected") {
        setTimelineError(
          sourceResult.reason instanceof ApiRequestError
            ? sourceResult.reason.feedback.title
            : "时间轴读取失败",
        );
        return;
      }

      const cloudDraft = cloudDraftResult.status === "fulfilled"
        && cloudDraftResult.value?.timeline.source_revision === sourceResult.value.source_revision
        ? cloudDraftResult.value : null;
      const savedAt = cloudDraft?.saved_at ?? null;
      savedAtRef.current = savedAt;
      setCloudSavedAt(savedAt);
      const cloudOrSource = toKirakaraTimeline(
        cloudDraft?.timeline ?? sourceResult.value,
      );
      const browserDraft = browserDraftResult.status === "fulfilled"
        && cloudDraftResult.status === "fulfilled"
        ? compatibleTimelineDraft(cloudOrSource, browserDraftResult.value, savedAt)
        : null;
      timelineDraftJobId.current = jobId;
      const restoredTimeline = browserDraft ?? cloudOrSource;
      history.current = createTimelineHistory(restoredTimeline);
      setHistoryAvailability({ canUndo: false, canRedo: false });
      setTimeline(restoredTimeline);
      setTimelineError(null);
      if (browserDraft) {
        setTimelineSaveState({
          phase: "restored",
          message: "已恢复此浏览器中的时间轴草稿",
        });
      } else if (cloudDraft) {
        setTimelineSaveState({
          phase: "restored",
          message: "已恢复云端时间轴草稿",
        });
      } else if (cloudDraftResult.status === "rejected") {
        setTimelineSaveState({
          phase: "error",
          message: cloudDraftResult.reason instanceof ApiRequestError
            ? cloudDraftResult.reason.feedback.title
            : "云端草稿读取失败",
        });
      } else {
        setTimelineSaveState({ phase: "idle" });
      }
    });
    return () => {
      active = false;
    };
  }, [jobId]);

  useEffect(() => {
    if (timelineDraftJobId.current !== jobId || !timeline || autosaveTrigger?.jobId !== jobId) return;
    const timer = setTimeout(() => {
      void saveBrowserReviewDraft(jobId, "timeline", { ...timeline, baseSavedAt: cloudSavedAt });
    }, 300);
    return () => clearTimeout(timer);
  }, [autosaveTrigger, cloudSavedAt, jobId, timeline]);

  useEffect(() => {
    if (!timeline || !autosaveTrigger || autosaveTrigger.jobId !== jobId) return;
    const version = autosaveTrigger.version;
    const targetJobId = jobId;
    const timeout = globalThis.setTimeout(() => {
      let review;
      try {
        review = timelineReviewPayload(timeline);
      } catch (reason) {
        if (
          componentActive.current
          && activeJobId.current === targetJobId
          && autosaveVersion.current === version
        ) {
          setTimelineSaveState({
            phase: "error",
            message: reason instanceof TimelineReviewValidationError
              ? reason.message
              : "时间轴校验失败",
          });
        }
        return;
      }

      const operation = saveQueue.current.then(async () => {
        if (!componentActive.current || activeJobId.current !== targetJobId) return null;
        if (
          componentActive.current
          && activeJobId.current === targetJobId
          && autosaveVersion.current === version
        ) {
          setTimelineSaveState({ phase: "saving" });
        }
        const saved = await saveTimelineReviewDraft(targetJobId, {
          ...review, base_saved_at: savedAtRef.current,
        });
        if (componentActive.current && activeJobId.current === targetJobId) {
          savedAtRef.current = saved.saved_at;
          setCloudSavedAt(saved.saved_at);
        }
        return saved;
      });
      saveQueue.current = operation.then(
        () => undefined,
        () => undefined,
      );
      void operation.then(
        (saved) => {
          if (
            saved && componentActive.current
            && activeJobId.current === targetJobId
            && autosaveVersion.current === version
          ) {
            setTimelineSaveState({ phase: "saved" });
          }
        },
        (reason) => {
          if (
            componentActive.current
            && activeJobId.current === targetJobId
            && autosaveVersion.current === version
          ) {
            setTimelineSaveState({
              phase: "error",
              refreshRequired: reason instanceof ApiRequestError && reason.status === 409,
              message: reason instanceof ApiRequestError
                ? reason.status === 409
                  ? "草稿或时间轴已更新，请刷新页面后继续。"
                  : reason.feedback.title
                : "时间轴自动保存失败",
            });
          }
        },
      );
    }, TIMELINE_AUTOSAVE_DELAY_MS);
    return () => globalThis.clearTimeout(timeout);
  }, [autosaveTrigger, jobId, timeline]);

  useEffect(() => {
    let active = true;
    const mobile = window.matchMedia("(max-width: 767px)").matches;
    detectKirakaraCapabilities(globalThis, mobile).then((capabilities) => {
      if (active) setCapabilities(capabilities);
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!video) return;
    let active = true;
    const nextUrl = URL.createObjectURL(video);
    Promise.resolve().then(() => {
      if (active) setVideoUrl(nextUrl);
    });
    return () => {
      active = false;
      URL.revokeObjectURL(nextUrl);
    };
  }, [video]);

  const updateFrame = useCallback(() => {
    const videoElement = videoRef.current;
    if (!videoElement) return;
    const loopTime = loopPlaybackTime(loopRange.current, videoElement.currentTime, videoElement.duration, !videoElement.paused);
    if (loopTime !== null) videoElement.currentTime = loopTime;
    const currentMs = Math.max(0, Math.round(videoElement.currentTime * 1000));
    setPlaybackMs((previous) => previous === currentMs ? previous : currentMs);
    if (timeline) {
      const protectedIndex = programmaticSeekLineRef.current;
      const protectedLine = protectedIndex === null ? undefined : timeline.lines[protectedIndex];
      const insidePreviewLead = protectedLine !== undefined
        && currentMs >= previewSeekMs(protectedLine.startMs, previewLeadMs, timeline.durationMs)
        && currentMs < protectedLine.startMs;
      if (!insidePreviewLead) programmaticSeekLineRef.current = null;
      const nextIndex = insidePreviewLead
        ? protectedIndex
        : activeTimelineLineIndex(timeline.lines, currentMs, playbackLineIndexRef.current);
      if (nextIndex !== playbackLineIndexRef.current) {
        playbackLineIndexRef.current = nextIndex;
        setPlaybackLineIndex(nextIndex);
      }
    }
    setFrame(
      timeline
        ? activeKirakaraFrame(timeline, currentMs)
        : null,
    );
  }, [previewLeadMs, timeline]);

  useEffect(() => {
    frameLoop.current ??= createPreviewFrameLoop({
      draw: updateFrame,
      isPlaying: () => videoRef.current?.paused === false,
    });
    frameLoop.current.setDraw(updateFrame);
  }, [updateFrame]);

  function updateStyle(nextStyle: KirakaraStyle) {
    setStyle(nextStyle);
    saveKirakaraStyle(window.localStorage, nextStyle);
  }

  const changePlaybackRate = useCallback((nextRate: number) => {
    const normalized = Math.min(2.5, Math.max(0.1, Math.round(nextRate * 10) / 10));
    if (normalized === playbackRate) return;
    const element = videoRef.current;
    if (element) element.playbackRate = normalized;
    setPlaybackRate(normalized);
    if (normalized !== 1) setLastNonDefaultRate(normalized);
    setRateNotice(normalized);
    if (rateNoticeTimer.current !== null) globalThis.clearTimeout(rateNoticeTimer.current);
    rateNoticeTimer.current = globalThis.setTimeout(() => setRateNotice(null), RATE_NOTICE_DURATION_MS);
  }, [playbackRate]);

  const selectEditingLine = useCallback((index: number) => {
    const selectedLine = timeline?.lines[index];
    if (!selectedLine) return;
    setEditingLineIndex(index);
    programmaticSeekLineRef.current = index;
    const element = videoRef.current;
    if (element) {
      seekVideoWithoutPlaybackChange(
        element,
        previewSeekMs(selectedLine.startMs, previewLeadMs, timeline.durationMs),
      );
      updateFrame();
      element.focus({ preventScroll: true });
    }
  }, [previewLeadMs, timeline, updateFrame]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const shortcut = playbackShortcut(event, event.target, shortcutBindings);
      if (shortcut === null) return;
      event.preventDefault();
      if (shortcut === PlaybackShortcut.SeekBackward || shortcut === PlaybackShortcut.SeekForward) {
        const element = videoRef.current;
        if (!element) return;
        const direction = shortcut === PlaybackShortcut.SeekBackward ? -1 : 1;
        seekVideoWithoutPlaybackChange(
          element,
          Math.round(element.currentTime * 1000) + direction * PLAYBACK_SEEK_STEP_MS,
        );
        updateFrame();
      } else if (shortcut === PlaybackShortcut.PreviousLine || shortcut === PlaybackShortcut.NextLine) {
        const currentIndex = editingLineIndex ?? playbackLineIndexRef.current;
        if (currentIndex === null || !timeline) return;
        const direction = shortcut === PlaybackShortcut.PreviousLine ? -1 : 1;
        const nextIndex = currentIndex + direction;
        if (nextIndex < 0 || nextIndex >= timeline.lines.length) return;
        selectEditingLine(nextIndex);
      } else if (shortcut === PlaybackShortcut.ReplayLine) {
        const currentIndex = editingLineIndex ?? playbackLineIndexRef.current;
        const currentLine = currentIndex === null ? undefined : timeline?.lines[currentIndex];
        const element = videoRef.current;
        if (currentIndex === null || !currentLine || !element) return;
        setEditingLineIndex(currentIndex);
        programmaticSeekLineRef.current = currentIndex;
        seekVideoWithoutPlaybackChange(element, currentLine.startMs);
        updateFrame();
        element.focus({ preventScroll: true });
      } else if (shortcut === PlaybackShortcut.ToggleLineLoop) {
        const currentIndex = editingLineIndex ?? playbackLineIndexRef.current;
        if (currentIndex === null || !timeline?.lines[currentIndex]) return;
        setEditingLineIndex(currentIndex);
        setLooping((current) => !current);
      } else if (shortcut === PlaybackShortcut.PreviousMora || shortcut === PlaybackShortcut.NextMora) {
        return;
      } else if (shortcut !== PlaybackShortcut.PlayToggle) {
        changePlaybackRate(playbackRateAfterShortcut(shortcut, playbackRate, lastNonDefaultRate));
      } else {
        const element = videoRef.current;
        if (!element) return;
        if (element.paused) {
          void element.play().catch(() => setPlaybackError("播放未能开始，请使用视频控件重试。"));
        } else {
          element.pause();
        }
      }
    }
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [changePlaybackRate, editingLineIndex, lastNonDefaultRate, playbackRate, selectEditingLine, shortcutBindings, timeline, updateFrame]);

  function saveTimelineChange(nextTimeline: KirakaraTimeline) {
    setHistoryAvailability({ canUndo: Boolean(history.current?.past.length), canRedo: Boolean(history.current?.future.length) });
    const version = autosaveVersion.current + 1;
    autosaveVersion.current = version;
    setTimeline(nextTimeline);
    setAutosaveTrigger({ jobId, version });
    setTimelineSaveState({ phase: "pending" });
  }

  function updateTimeline(nextTimeline: KirakaraTimeline, group?: string) {
    if (!history.current) history.current = createTimelineHistory(nextTimeline);
    else history.current = recordTimelineEdit(history.current, nextTimeline, group);
    saveTimelineChange(nextTimeline);
  }

  function navigateHistory(direction: "undo" | "redo") {
    if (!history.current) return;
    history.current = direction === "undo" ? undoTimelineEdit(history.current) : redoTimelineEdit(history.current);
    saveTimelineChange(history.current.present);
  }

  const loopLine = useCallback((range: PlaybackRange | null) => {
    loopRange.current = range;
    setPlaybackError(null);
    const element = videoRef.current;
    if (!range || !element) return;
    if (Number.isFinite(element.duration) && range.startMs >= element.duration * 1000) {
      setPlaybackError("当前句超出视频时长");
    }
  }, []);

  function retryTimelineSave() {
    if (!timeline) return;
    const version = autosaveVersion.current + 1;
    autosaveVersion.current = version;
    setAutosaveTrigger({ jobId, version });
    setTimelineSaveState({ phase: "pending" });
  }

  const stopDrawing = useCallback(() => {
    frameLoop.current?.stop();
  }, []);

  const startDrawing = useCallback(() => {
    frameLoop.current?.start();
  }, []);

  useEffect(() => stopDrawing, [stopDrawing]);

  function selectVideo(file: File | null) {
    if (!file) return;
    rememberLocalVideo(jobId, file);
    setVideo(file);
    setSelectionWarning(
      file.name === expectedVideoName
        ? null
        : `当前选择的是 ${file.name}，任务原文件为 ${expectedVideoName}。`,
    );
  }

  function seekPreview(milliseconds: number) {
    const element = videoRef.current;
    if (!element) return;
    programmaticSeekLineRef.current = editingLineIndex;
    seekVideoWithoutPlaybackChange(element, milliseconds);
    updateFrame();
  }

  function locatePlaybackLine() {
    if (playbackLineIndex === null) return;
    setEditingLineIndex(playbackLineIndex);
  }

  function updatePreviewLead(value: string | number | null) {
    const normalized = savePreviewLeadMs(window.localStorage, value);
    setPreviewLeadMs(normalized);
  }

  function updateShortcut(shortcut: keyof PlaybackShortcutBindings, value: string) {
    const key = normalizePlaybackShortcutKey(value);
    if (key === null) {
      setShortcutError("快捷键仅支持单个英文字母、数字或方括号");
      return;
    }
    const duplicate = Object.entries(shortcutBindings).find(
      ([configuredShortcut, configuredKey]) => configuredShortcut !== shortcut && configuredKey === key,
    );
    if (duplicate) {
      setShortcutError(`快捷键 ${key.toUpperCase()} 已被其他操作使用`);
      return;
    }
    const nextBindings = savePlaybackShortcutBindings(window.localStorage, {
      ...shortcutBindings,
      [shortcut]: key,
    });
    setShortcutBindings(nextBindings);
    setShortcutError(null);
  }

  function resetShortcuts() {
    const defaults = savePlaybackShortcutBindings(window.localStorage, DEFAULT_PLAYBACK_SHORTCUT_BINDINGS);
    setShortcutBindings(defaults);
    setShortcutError(null);
  }

  return (
    <section className="mt-6 border-t pt-6" aria-labelledby="kirakara-preview-heading">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-base font-bold text-primary">Kirakara 引擎</p>
          <h2 id="kirakara-preview-heading" className="mt-1 text-xl font-bold">
            浏览器本地预览
          </h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            时间轴调整会自动保存在此浏览器，刷新页面后可继续。
          </p>
        </div>
        <Film className="size-5 shrink-0 text-muted-foreground" />
      </div>

      {!video ? (
        <div className="mt-4 border-l-2 border-primary pl-4">
          <p className="text-sm leading-6 text-muted-foreground">
            请选择任务使用的原视频 <strong className="text-foreground">{expectedVideoName}</strong>。
          </p>
          <label className="focus-ring mt-3 inline-flex cursor-pointer items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-sm font-semibold transition hover:bg-muted">
            <FolderOpen className="size-4" />
            重新选择原视频
            <input
              type="file"
              accept="video/mp4,.mp4"
              className="sr-only"
              onChange={(event) => selectVideo(event.target.files?.[0] ?? null)}
            />
          </label>
        </div>
      ) : (
        <div
          data-kirakara-workbench="desktop-fit"
          className="mt-4 grid items-start gap-3 lg:grid-cols-[minmax(18rem,0.7fr)_minmax(0,1.55fr)] xl:grid-cols-[minmax(20rem,0.65fr)_minmax(0,1.65fr)]"
        >
          <div
            data-kirakara-preview-panel="true"
            className="min-w-0 lg:col-span-2 lg:row-start-1"
          >
            <div
              data-kirakara-preview-surface="true"
              className="relative aspect-video w-full overflow-hidden rounded-lg bg-black"
            >
              {videoUrl && (
                <video
                  ref={assignVideoElement}
                  src={videoUrl}
                  controls
                  tabIndex={0}
                  playsInline
                  preload="metadata"
                  className="size-full object-contain"
                  onLoadedMetadata={(event) => {
                    event.currentTarget.playbackRate = playbackRate;
                    updateFrame();
                  }}
                  onTimeUpdate={updateFrame}
                  onSeeked={updateFrame}
                  onPlay={() => {
                    setIsPlaying(true);
                    startDrawing();
                  }}
                  onEnded={() => {
                    setIsPlaying(false);
                    stopDrawing();
                    updateFrame();
                  }}
                  onPause={() => {
                    setIsPlaying(false);
                    stopDrawing();
                    updateFrame();
                  }}
                />
              )}
              <KirakaraCanvasFrame frame={frame} style={style} />
              <PlaybackRateNotice rate={rateNotice} />
              {!timeline && !timelineError && (
                <div className="pointer-events-none absolute inset-0 flex items-center justify-center gap-2 bg-black/45 text-sm text-white">
                  <LoaderCircle className="size-4 animate-spin" />
                  正在读取时间轴
                </div>
              )}
            </div>
            <div data-playback-controls="true" className="mt-3 flex flex-wrap items-center gap-3 text-sm">
              <label className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                播放倍速
                <select
                  aria-label="播放倍速"
                  value={playbackRate}
                  onChange={(event) => changePlaybackRate(Number(event.target.value))}
                  className="focus-ring h-9 rounded-md border bg-background px-2 text-sm text-foreground"
                >
                  {PLAYBACK_RATES.map((rate) => (
                    <option key={rate} value={rate}>{rate.toFixed(1)}×</option>
                  ))}
                </select>
              </label>
              <output
                data-current-video-time="true"
                aria-label="当前视频时间"
                className="font-mono tabular-nums text-foreground"
              >
                {formatPlaybackSeconds(playbackMs)}
              </output>
              <button
                type="button"
                data-locate-playback-line="true"
                disabled={playbackLineIndex === null}
                onClick={locatePlaybackLine}
                className="focus-ring h-9 rounded-md border px-3 text-xs font-semibold hover:bg-muted disabled:opacity-40"
              >
                定位歌词
              </button>
              <span className="sr-only" data-playing={isPlaying}>播放状态</span>
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
              <span>
                {!capabilities
                  ? "正在检查本地编码能力"
                  : kirakaraSupportMessage(capabilities)}
              </span>
              <label className="focus-ring cursor-pointer rounded-sm font-medium text-foreground underline-offset-4 hover:underline">
                更换视频
                <input
                  type="file"
                  accept="video/mp4,.mp4"
                  className="sr-only"
                  onChange={(event) => selectVideo(event.target.files?.[0] ?? null)}
                />
              </label>
            </div>
          </div>

          <div
            data-kirakara-timeline-panel="true"
            className={`min-w-0 lg:col-start-2 lg:row-start-2 ${
              timeline
                ? "rounded-lg border bg-background/40 p-3"
                : "hidden"
            }`}
          >
            {timeline && (
              <>
                <div
                  data-timeline-autosave={timelineSaveState.phase}
                  aria-live="polite"
                  className="mb-3 flex flex-wrap items-center justify-end gap-2 text-xs text-muted-foreground"
                >
                  {timelineSaveState.phase === "saving" ? (
                    <LoaderCircle className="size-3.5 animate-spin" />
                  ) : (
                    <Cloud className="size-3.5" />
                  )}
                  <span>
                    {timelineSaveState.phase === "pending"
                      ? "等待保存到云端"
                      : timelineSaveState.phase === "saving"
                        ? "正在保存时间轴"
                        : timelineSaveState.phase === "saved"
                          ? "时间轴已保存到云端"
                          : timelineSaveState.phase === "restored"
                            ? timelineSaveState.message ?? "已恢复时间轴草稿"
                            : timelineSaveState.phase === "error"
                              ? timelineSaveState.message ?? "时间轴自动保存失败"
                              : "时间轴修改会自动保存到云端"}
                  </span>
                  {timelineSaveState.phase === "error" && (
                    <button
                      type="button"
                      onClick={timelineSaveState.refreshRequired
                        ? () => window.location.reload() : retryTimelineSave}
                      className="focus-ring inline-flex items-center gap-1 rounded-sm font-medium text-foreground underline-offset-4 hover:underline"
                    >
                      <RefreshCw className="size-3.5" />
                      {timelineSaveState.refreshRequired ? "刷新页面" : "重试保存"}
                    </button>
                  )}
                </div>
                <KirakaraReviewEditor
                  key={jobId}
                  timeline={timeline}
                  audioSource={video}
                  editingLineIndex={editingLineIndex}
                  previewLeadMs={previewLeadMs}
                  shortcutBindings={shortcutBindings}
                  onEditingLineChange={selectEditingLine}
                  onChange={updateTimeline}
                  onSeek={seekPreview}
                  canUndo={historyAvailability.canUndo}
                  canRedo={historyAvailability.canRedo}
                  onUndo={() => navigateHistory("undo")}
                  onRedo={() => navigateHistory("redo")}
                  looping={looping}
                  onLoopChange={setLooping}
                  onLoop={loopLine}
                />
                <details data-timing-settings="true" className="mt-4 rounded-md border bg-background/60">
                  <summary className="focus-ring flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-semibold [&::-webkit-details-marker]:hidden">
                    <Settings2 className="size-4" />
                    调轴设置
                  </summary>
                  <div className="space-y-3 border-t p-3">
                    <label className="block text-xs font-medium text-muted-foreground">
                      复听提前量（ms）
                      <input
                        type="number"
                        min="0"
                        max="2000"
                        step="1"
                        value={previewLeadMs}
                        onChange={(event) => updatePreviewLead(event.target.value)}
                        className="focus-ring mt-1 block w-full rounded-md border bg-background px-3 py-2 text-sm text-foreground"
                      />
                    </label>
                    <button
                      type="button"
                      onClick={() => updatePreviewLead(DEFAULT_PREVIEW_LEAD_MS)}
                      className="focus-ring rounded-md border px-3 py-2 text-xs font-semibold hover:bg-muted"
                    >
                      恢复默认值
                    </button>
                    <div className="grid gap-4 border-t pt-3 sm:grid-cols-2">
                      {[
                        { title: "快速定位", settings: QUICK_LINE_SHORTCUT_SETTINGS },
                        { title: "Mora 选择", settings: MORA_SHORTCUT_SETTINGS },
                        { title: "播放倍速", settings: PLAYBACK_RATE_SHORTCUT_SETTINGS },
                      ].map((group) => (
                        <fieldset key={group.title} className="min-w-0">
                          <legend className="text-xs font-bold text-foreground">{group.title}</legend>
                          <div className="mt-2 grid grid-cols-2 gap-2">
                            {group.settings.map(({ shortcut, label }) => (
                              <label key={shortcut} className="text-xs font-medium text-muted-foreground">
                                {label}
                                <input
                                  aria-label={`快捷键：${label}`}
                                  value={shortcutBindings[shortcut].toUpperCase()}
                                  readOnly
                                  onKeyDown={(event) => {
                                    event.preventDefault();
                                    if (event.repeat || event.ctrlKey || event.metaKey || event.altKey) return;
                                    updateShortcut(shortcut, event.key);
                                  }}
                                  className="focus-ring mt-1 block h-9 w-full cursor-pointer rounded-md border bg-background px-3 text-center text-sm font-bold uppercase text-foreground"
                                />
                              </label>
                            ))}
                          </div>
                        </fieldset>
                      ))}
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-xs leading-5 text-muted-foreground">点击快捷键输入框，再按一个字母、数字或方括号即可替换。</p>
                      <button
                        type="button"
                        onClick={resetShortcuts}
                        className="focus-ring rounded-md border px-3 py-2 text-xs font-semibold hover:bg-muted"
                      >
                        恢复快捷键默认值
                      </button>
                    </div>
                    {shortcutError && <p role="alert" className="text-xs text-destructive">{shortcutError}</p>}
                    <p className="text-xs leading-5 text-muted-foreground">方向键微调边界；空格播放或暂停。快捷键在文本输入和下拉框中不会触发。</p>
                  </div>
                </details>
                {playbackError && <p role="alert" className="mt-2 text-sm text-destructive">{playbackError}</p>}
              </>
            )}
          </div>

          <div
            data-kirakara-controls-panel="true"
            className={`min-w-0 lg:col-start-1 lg:row-start-2 ${
              timeline
                ? "rounded-lg border bg-background/40 p-3"
                : "hidden"
            }`}
          >
            {timeline && (
              <div className="min-w-0">
                <div role="tablist" aria-label="歌词与字幕样式" className="mb-3 grid grid-cols-2 rounded-md border bg-muted/30 p-1">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={sideTab === WorkbenchSideTab.Lyrics}
                    onClick={() => setSideTab(WorkbenchSideTab.Lyrics)}
                    className={`focus-ring rounded px-3 py-2 text-sm font-semibold ${sideTab === WorkbenchSideTab.Lyrics ? "bg-background shadow-sm" : "text-muted-foreground"}`}
                  >
                    滚动歌词
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={sideTab === WorkbenchSideTab.Style}
                    onClick={() => setSideTab(WorkbenchSideTab.Style)}
                    className={`focus-ring rounded px-3 py-2 text-sm font-semibold ${sideTab === WorkbenchSideTab.Style ? "bg-background shadow-sm" : "text-muted-foreground"}`}
                  >
                    字幕样式
                  </button>
                </div>
                <div
                  data-kirakara-tab-scroll-area="true"
                  className="min-w-0"
                >
                  {sideTab === WorkbenchSideTab.Lyrics ? (
                    <KirakaraLyricNavigator
                      timeline={timeline}
                      playbackLineIndex={playbackLineIndex}
                      editingLineIndex={editingLineIndex}
                      onSelect={selectEditingLine}
                    />
                  ) : (
                    <KirakaraStyleEditor style={style} onChange={updateStyle} />
                  )}
                </div>
              </div>
            )}
          </div>

        </div>
      )}
          <section
            data-kirakara-export-panel="true"
            aria-labelledby="kirakara-export-heading"
            className={`mt-4 min-w-0 ${
              timeline
                ? "rounded-lg border bg-background/40 p-3"
                : "hidden"
            }`}
          >
            {timeline && (
              <>
                <h3 id="kirakara-export-heading" className="mb-3 text-base font-bold">导出</h3>
                <div className="min-w-0 space-y-3 [&>div]:mt-0 [&>div]:border-t-0 [&>div]:pt-0">
                <ReviewedDataDownloads
                  jobId={jobId}
                  videoName={expectedVideoName}
                  timeline={timeline}
                  style={style}
                />
                  {exportDisabled && <p className="text-sm text-muted-foreground">服务器正在处理当前导出，完成后可继续导出其他版本。当前编辑结果会继续保留。</p>}
                  {capabilities ? (
                    <KirakaraRenderActions
                      capabilities={capabilities}
                      video={video}
                      timeline={timeline}
                      style={style}
                      jobId={jobId}
                      disabled={exportDisabled}
                      availableModes={availableModes}
                      resultVersion={resultVersion}
                      job={job}
                      rerender={hasCloudResult}
                      onCloudRenderQueued={onCloudRenderQueued}
                    />
                  ) : (
                    <p className="text-xs text-muted-foreground">正在检查可用的导出方式…</p>
                  )}
                </div>
              </>
            )}
          </section>

      {(timelineError || selectionWarning) && (
        <p className="mt-3 text-sm text-destructive" role="alert">
          {timelineError ?? selectionWarning}
        </p>
      )}

      <aside className="mt-6 border-t pt-4 text-sm leading-relaxed text-muted-foreground" aria-labelledby="kirakara-acknowledgements-heading">
        <h3 id="kirakara-acknowledgements-heading" className="font-semibold text-foreground">特别鸣谢</h3>
        <ul className="mt-2 list-disc space-y-2 break-words pl-5 [&_a]:font-semibold [&_a]:text-primary [&_a]:underline [&_a]:underline-offset-4">
          <li>
            <a className="focus-ring rounded-sm" href="https://github.com/FMPeach" target="_blank" rel="noopener noreferrer">FMPeach</a>
            开发的
            <a className="focus-ring rounded-sm" href="https://github.com/FMPeach/Kirakara-Player" target="_blank" rel="noopener noreferrer">Kirakara-Player</a>
            。本项目的字幕预览、样式配置与渲染适配参考了该项目。
          </li>
          <li>
            <a className="focus-ring rounded-sm" href="https://github.com/moriwx" target="_blank" rel="noopener noreferrer">moriwx</a>
            开发的
            <a className="focus-ring rounded-sm" href="https://github.com/moriwx/FA-Kara" target="_blank" rel="noopener noreferrer">FA-Kara</a>
            。本项目的歌词发音标记、非静音处理与 MMS 强制对齐参考并适配了该项目。
          </li>
        </ul>
      </aside>
    </section>
  );
}
