export type CloudAlignedMora = {
  reading: string;
  start_ms: number;
  end_ms: number;
  matched: boolean;
  confidence: number;
};

export type CloudAlignedToken = {
  surface: string;
  reading: string;
  start_ms: number;
  end_ms: number;
  confidence: number;
  moras: CloudAlignedMora[];
};

export type CloudAlignedLine = {
  surface: string;
  reading: string;
  start_ms: number;
  end_ms: number;
  confidence: number;
  tokens: CloudAlignedToken[];
};

export type CloudLyricTimeline = {
  confidence: number;
  lines: CloudAlignedLine[];
  warnings: string[];
};

export type KirakaraMora = {
  reading: string;
  startMs: number;
  endMs: number;
  matched: boolean;
};

export type KirakaraRuby = {
  text: string;
  startCharacter: number;
  endCharacter: number;
};

export type KirakaraRenderUnit = {
  text: string;
  reading: string;
  startMs: number;
  endMs: number;
  moras: KirakaraMora[];
  ruby?: KirakaraRuby[];
};

export type KirakaraLine = {
  text: string;
  reading: string;
  startMs: number;
  endMs: number;
  units: KirakaraRenderUnit[];
};

export type KirakaraTimeline = {
  confidence: number;
  warnings: string[];
  durationMs: number;
  lines: KirakaraLine[];
};

export type KirakaraFrameUnit = {
  text: string;
  progress: number;
  characters?: KirakaraFrameCharacter[];
  ruby: KirakaraRuby[];
};

export type KirakaraFrameCharacter = {
  text: string;
  progress: number;
};

export type KirakaraFrameLine = {
  slot: "upper" | "lower";
  text: string;
  units: KirakaraFrameUnit[];
};

export type KirakaraFrame = {
  lines: KirakaraFrameLine[];
};

const SECTION_LEAD_MS = 3000;
const LONG_INTERLUDE_MS = 12000;
const EXIT_HOLD_MS = 2000;

function normalizedRange(startMs: number, endMs: number) {
  const start = Math.max(0, Math.round(startMs));
  return { startMs: start, endMs: Math.max(start, Math.round(endMs)) };
}

function normalizeKana(text: string): string {
  return text.normalize("NFKC").replace(/[\u30a1-\u30f6]/g, (character) =>
    String.fromCharCode(character.charCodeAt(0) - 0x60),
  );
}

function isKanji(character: string): boolean {
  const codePoint = character.codePointAt(0) ?? 0;
  return (
    (codePoint >= 0x3400 && codePoint <= 0x4dbf) ||
    (codePoint >= 0x4e00 && codePoint <= 0x9fff)
  );
}

export function kanjiRuby(surface: string, reading: string): KirakaraRuby[] {
  const characters = [...surface];
  if (!characters.some(isKanji) || !reading.trim()) return [];
  return [
    {
      text: normalizeKana(reading),
      startCharacter: 0,
      endCharacter: characters.length,
    },
  ];
}

export function toKirakaraTimeline(source: CloudLyricTimeline): KirakaraTimeline {
  const lines = source.lines.map((line) => {
    const lineRange = normalizedRange(line.start_ms, line.end_ms);
    return {
      text: line.surface,
      reading: line.reading,
      ...lineRange,
      units: line.tokens.map((token) => ({
        text: token.surface,
        reading: token.reading,
        ...normalizedRange(token.start_ms, token.end_ms),
        moras: token.moras.map((mora) => ({
          reading: mora.reading,
          ...normalizedRange(mora.start_ms, mora.end_ms),
          matched: mora.matched,
        })),
        ruby: kanjiRuby(token.surface, token.reading),
      })),
    };
  });

  return {
    confidence: source.confidence,
    warnings: [...source.warnings],
    durationMs: lines.reduce((latest, line) => Math.max(latest, line.endMs), 0),
    lines,
  };
}

function displayStart(lines: KirakaraLine[], index: number): number {
  const line = lines[index];
  const previous = lines[index - 1];
  if (!previous || line.startMs - previous.endMs >= LONG_INTERLUDE_MS) {
    return Math.max(0, line.startMs - SECTION_LEAD_MS);
  }
  return previous.startMs;
}

function displayEnd(lines: KirakaraLine[], index: number): number {
  const nextInSlot = lines[index + 2];
  if (nextInSlot) return displayStart(lines, index + 2);
  return lines[index].endMs + EXIT_HOLD_MS;
}

function clampProgress(progress: number): number {
  return Math.min(1, Math.max(0, progress));
}

function unitSequencePosition(unit: KirakaraRenderUnit, playbackMs: number): {
  position: number;
  segmentCount: number;
} {
  if (unit.moras.length === 0) {
    const duration = unit.endMs - unit.startMs;
    const position = duration > 0
      ? clampProgress((playbackMs - unit.startMs) / duration)
      : playbackMs >= unit.endMs ? 1 : 0;
    return { position, segmentCount: 1 };
  }

  for (let index = 0; index < unit.moras.length; index += 1) {
    const mora = unit.moras[index];
    const startMs = Math.max(unit.startMs, mora.startMs);
    const endMs = Math.min(unit.endMs, Math.max(startMs, mora.endMs));
    if (playbackMs <= startMs) {
      return { position: index, segmentCount: unit.moras.length };
    }
    if (playbackMs < endMs) {
      const duration = endMs - startMs;
      return {
        position: index + (duration > 0 ? (playbackMs - startMs) / duration : 1),
        segmentCount: unit.moras.length,
      };
    }
  }

  return { position: unit.moras.length, segmentCount: unit.moras.length };
}

function unitFrame(unit: KirakaraRenderUnit, playbackMs: number): KirakaraFrameUnit {
  const characters = [...unit.text];
  const { position, segmentCount } = unitSequencePosition(unit, playbackMs);
  const progress = clampProgress(position / segmentCount);
  const characterPosition = progress * characters.length;

  return {
    text: unit.text,
    ruby: unit.ruby ?? kanjiRuby(unit.text, unit.reading),
    progress,
    characters: characters.map((text, index) => ({
      text,
      progress: clampProgress(characterPosition - index),
    })),
  };
}

export function activeKirakaraFrame(
  timeline: KirakaraTimeline,
  playbackMs: number,
): KirakaraFrame | null {
  const lines = timeline.lines
    .map((line, index): KirakaraFrameLine | null => {
      if (
        playbackMs < displayStart(timeline.lines, index) ||
        playbackMs >= displayEnd(timeline.lines, index)
      ) {
        return null;
      }
      return {
        slot: index % 2 === 0 ? "upper" : "lower",
        text: line.text,
        units: line.units.map((unit) => unitFrame(unit, playbackMs)),
      };
    })
    .filter((line): line is KirakaraFrameLine => line !== null)
    .sort((left, right) => (left.slot === "upper" ? -1 : right.slot === "upper" ? 1 : 0));

  return lines.length > 0 ? { lines } : null;
}
