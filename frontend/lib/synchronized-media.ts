export type SyncableMedia = EventTarget & {
  currentTime: number;
  duration: number;
  paused: boolean;
  play: () => Promise<unknown>;
  pause: () => void;
};

const TIME_DRIFT_TOLERANCE_SECONDS = 0.12;

function targetTime(source: SyncableMedia, target: SyncableMedia): number {
  if (Number.isFinite(target.duration) && target.duration >= 0) {
    return Math.min(source.currentTime, target.duration);
  }
  return source.currentTime;
}

function copyTime(
  source: SyncableMedia,
  target: SyncableMedia,
  force = false,
) {
  const nextTime = targetTime(source, target);
  if (
    force ||
    Math.abs(target.currentTime - nextTime) > TIME_DRIFT_TOLERANCE_SECONDS
  ) {
    target.currentTime = nextTime;
  }
}

export function synchronizeMediaPair(
  first: SyncableMedia,
  second: SyncableMedia,
): () => void {
  const cleanups: Array<() => void> = [];

  const connect = (source: SyncableMedia, target: SyncableMedia) => {
    const listen = (event: string, handler: EventListener) => {
      source.addEventListener(event, handler);
      cleanups.push(() => source.removeEventListener(event, handler));
    };

    listen("seeking", () => copyTime(source, target, true));
    listen("seeked", () => copyTime(source, target, true));
    listen("timeupdate", () => copyTime(source, target));
    listen("play", () => {
      copyTime(source, target, true);
      void target.play().catch(() => undefined);
    });
    listen("pause", () => {
      copyTime(source, target, true);
      target.pause();
    });
  };

  copyTime(first, second, true);
  connect(first, second);
  connect(second, first);

  return () => cleanups.forEach((cleanup) => cleanup());
}
