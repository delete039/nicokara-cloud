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
  alignment_engine?: string;
  alignment_model?: string | null;
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
  ruby: KirakaraFrameRuby[];
};

export type KirakaraFrameCharacter = {
  text: string;
  progress: number;
};

export type KirakaraFrameRuby = KirakaraRuby & {
  characters?: KirakaraFrameCharacter[];
};

export type KirakaraFrameLine = {
  slot: "upper" | "lower";
  text: string;
  units: KirakaraFrameUnit[];
  opacity?: number;
  indicatorOpacities?: number[];
};

export type KirakaraFrame = {
  lines: KirakaraFrameLine[];
};

export type KirakaraLayoutLine = {
  line: KirakaraLine;
  paragraph: number;
  lineInParagraph: number;
  entryMs: number;
  walkDoneMs: number;
  isFirstInParagraph: boolean;
  isLastInParagraph: boolean;
};

const ENTRY_BUFFER_MS = 666 + 500 + 3000;
const EXIT_HOLD_MS = 2000;
const FADE_DURATION_MS = 666;
const INDICATOR_DURATION_MS = 3000;
const WALK_PROTECT_MS = 1000;
const WALK_PROTECT_MARGIN_MS = 2500;

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

export function closeLineMoraGaps(line: KirakaraLine): KirakaraLine {
  const units = line.units.map((unit) => ({
    ...unit,
    moras: unit.moras.map((mora) => ({ ...mora })),
  }));
  const references = units.flatMap((unit, unitIndex) =>
    unit.moras.map((_, moraIndex) => ({ unitIndex, moraIndex })),
  );

  for (let index = 0; index < references.length - 1; index += 1) {
    const current = references[index];
    const next = references[index + 1];
    const currentMora = units[current.unitIndex].moras[current.moraIndex];
    const nextMora = units[next.unitIndex].moras[next.moraIndex];
    if (currentMora.endMs >= nextMora.startMs) continue;

    const boundary = nextMora.startMs;
    currentMora.endMs = boundary;
    if (current.unitIndex === next.unitIndex) continue;

    units[current.unitIndex].endMs = boundary;
    for (
      let unitIndex = current.unitIndex + 1;
      unitIndex < next.unitIndex;
      unitIndex += 1
    ) {
      units[unitIndex].startMs = boundary;
      units[unitIndex].endMs = boundary;
    }
    units[next.unitIndex].startMs = boundary;
  }

  return { ...line, units };
}

export function toKirakaraTimeline(source: CloudLyricTimeline): KirakaraTimeline {
  const lines = source.lines.map((line) => {
    const lineRange = normalizedRange(line.start_ms, line.end_ms);
    return closeLineMoraGaps({
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
    });
  });

  return {
    confidence: source.confidence,
    warnings: [...source.warnings],
    durationMs: lines.reduce((latest, line) => Math.max(latest, line.endMs), 0),
    lines,
  };
}

export function layoutKirakaraParagraphs(
  lines: KirakaraLine[],
): KirakaraLayoutLine[] {
  let paragraph = 0;
  let lineInParagraph = 0;
  let paragraphStartMs = lines[0]?.startMs ?? 0;
  const layout = lines.map((line, index): KirakaraLayoutLine => {
    const previous = lines[index - 1];
    if (
      previous &&
      line.startMs - previous.endMs > ENTRY_BUFFER_MS + EXIT_HOLD_MS
    ) {
      paragraph += 1;
      lineInParagraph = 0;
      paragraphStartMs = line.startMs;
    }
    const value: KirakaraLayoutLine = {
      line,
      paragraph,
      lineInParagraph,
      entryMs: line.startMs - ENTRY_BUFFER_MS,
      walkDoneMs: line.endMs,
      isFirstInParagraph: false,
      isLastInParagraph: false,
    };
    lineInParagraph += 1;
    if (value.lineInParagraph === 1) {
      value.entryMs = paragraphStartMs - ENTRY_BUFFER_MS;
    }
    return value;
  });

  for (let index = 0; index < layout.length - 2; index += 1) {
    const current = layout[index];
    const nextInSlot = layout[index + 2];
    if (nextInSlot.paragraph !== current.paragraph) continue;
    if (nextInSlot.entryMs > current.line.endMs + EXIT_HOLD_MS) {
      current.walkDoneMs = current.line.endMs + EXIT_HOLD_MS;
      nextInSlot.entryMs = current.walkDoneMs;
    }
  }

  for (let index = 0; index < layout.length - 2; index += 1) {
    const current = layout[index];
    const nextInSlot = layout[index + 2];
    if (nextInSlot.paragraph !== current.paragraph) continue;
    const proposedWalkDoneMs = current.walkDoneMs + WALK_PROTECT_MS;
    if (nextInSlot.line.startMs >= proposedWalkDoneMs + WALK_PROTECT_MARGIN_MS) {
      current.walkDoneMs = proposedWalkDoneMs;
    }
  }

  return layout.map((value, index) => ({
    ...value,
    isFirstInParagraph: value.lineInParagraph <= 1,
    isLastInParagraph:
      !layout[index + 1] || layout[index + 1].paragraph !== value.paragraph,
  }));
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

  const segments = moraSegments(unit);
  for (let index = 0; index < segments.length; index += 1) {
    const { startMs, endMs } = segments[index];
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

function moraSegments(unit: KirakaraRenderUnit) {
  return unit.moras.map((mora, index) => {
    const previous = unit.moras[index - 1];
    const startMs = Math.max(
      unit.startMs,
      index === 0 ? unit.startMs : previous.endMs,
    );
    return {
      text: normalizeKana(mora.reading),
      startMs,
      endMs: Math.min(
        unit.endMs,
        Math.max(
          startMs,
          index === unit.moras.length - 1 ? unit.endMs : mora.endMs,
        ),
      ),
    };
  });
}

function frameRuby(
  unit: KirakaraRenderUnit,
  ruby: KirakaraRuby,
  playbackMs: number,
  fallbackProgress: number,
): KirakaraFrameRuby {
  const segments = moraSegments(unit);
  const segmentText = segments.map(({ text }) => text).join("");
  if (segments.length <= 1 || segmentText !== ruby.text) {
    const characters = [...ruby.text];
    const position = fallbackProgress * characters.length;
    return {
      ...ruby,
      characters: characters.map((text, index) => ({
        text,
        progress: clampProgress(position - index),
      })),
    };
  }

  return {
    ...ruby,
    characters: segments.flatMap(({ text, startMs, endMs }) => {
      const characters = [...text];
      const duration = endMs - startMs;
      return characters.map((character, index) => {
        const characterStartMs = startMs + duration * index / characters.length;
        const characterEndMs = startMs + duration * (index + 1) / characters.length;
        return {
          text: character,
          progress: characterEndMs > characterStartMs
            ? clampProgress(
                (playbackMs - characterStartMs) /
                  (characterEndMs - characterStartMs),
              )
            : playbackMs >= characterEndMs ? 1 : 0,
        };
      });
    }),
  };
}

function lineOpacity(value: KirakaraLayoutLine, playbackMs: number): number {
  let opacity = 1;
  if (
    value.isFirstInParagraph &&
    playbackMs < value.entryMs + FADE_DURATION_MS
  ) {
    opacity = Math.max(0, (playbackMs - value.entryMs) / FADE_DURATION_MS);
  }
  const exitMs = value.line.endMs + EXIT_HOLD_MS;
  if (
    value.isLastInParagraph &&
    playbackMs > exitMs - FADE_DURATION_MS
  ) {
    opacity = Math.min(
      opacity,
      Math.max(0, (exitMs - playbackMs) / FADE_DURATION_MS),
    );
  }
  return clampProgress(opacity);
}

function indicatorOpacities(
  value: KirakaraLayoutLine,
  playbackMs: number,
): number[] | undefined {
  if (value.lineInParagraph !== 0) return undefined;
  const quarterMs = INDICATOR_DURATION_MS / 4;
  const opacities = [0, 1, 2, 3].map((index) =>
    playbackMs >= value.line.startMs - INDICATOR_DURATION_MS + index * quarterMs
      ? 0
      : 1,
  );
  return opacities.reverse();
}

function unitFrame(unit: KirakaraRenderUnit, playbackMs: number): KirakaraFrameUnit {
  const characters = [...unit.text];
  const { position, segmentCount } = unitSequencePosition(unit, playbackMs);
  const progress = clampProgress(position / segmentCount);
  const characterPosition = progress * characters.length;

  return {
    text: unit.text,
    ruby: (unit.ruby ?? kanjiRuby(unit.text, unit.reading)).map((ruby) =>
      frameRuby(unit, ruby, playbackMs, progress),
    ),
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
  const selected: Partial<Record<"upper" | "lower", {
    frame: KirakaraFrameLine;
    paragraph: number;
    walking: boolean;
  }>> = {};

  for (const value of layoutKirakaraParagraphs(timeline.lines)) {
    const { line } = value;
    if (
      playbackMs < value.entryMs ||
      playbackMs > line.endMs + EXIT_HOLD_MS
    ) continue;

    const slot = value.lineInParagraph % 2 === 0 ? "upper" : "lower";
    const current = selected[slot];
    if (current?.paragraph === value.paragraph && current.walking) continue;
    selected[slot] = {
      paragraph: value.paragraph,
      walking: playbackMs < value.walkDoneMs,
      frame: {
        slot,
        text: line.text,
        units: line.units.map((unit) => unitFrame(unit, playbackMs)),
        opacity: lineOpacity(value, playbackMs),
        indicatorOpacities: indicatorOpacities(value, playbackMs),
      },
    };
  }

  const lines = [selected.upper?.frame, selected.lower?.frame]
    .filter((line): line is KirakaraFrameLine => line !== undefined);

  return lines.length > 0 ? { lines } : null;
}
