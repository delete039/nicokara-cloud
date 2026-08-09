from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from app.ai.whisper import TranscriptDocument
from app.alignment.japanese import normalize_reading, split_moras
from app.alignment.models import (
    AlignedLine,
    AlignedMora,
    AlignedToken,
    LyricTimeline,
)
from app.lyrics.models import LyricDocument


@dataclass(frozen=True)
class _TargetMora:
    line_index: int
    token_index: int
    reading: str


@dataclass(frozen=True)
class _TimedMora:
    reading: str
    start_ms: int
    end_ms: int


class AlignmentQualityError(ValueError):
    """Raised when audio-derived anchors are insufficient for a timeline."""


class LyricTimelineAligner:
    def align(
        self,
        lyrics: LyricDocument,
        transcript: TranscriptDocument,
    ) -> LyricTimeline:
        targets = self._lyric_moras(lyrics)
        observations = self._transcript_moras(transcript)
        if not observations:
            raise AlignmentQualityError("No ASR word timestamps were detected")
        line_windows = self._line_windows(lyrics, transcript)
        line_windows = self._complete_line_windows(
            lyrics,
            line_windows,
            observations,
        )
        matches = self._matches(targets, observations, line_windows)
        match_ratio = len(matches) / len(targets) if targets else 0.0
        if match_ratio < 0.15:
            raise AlignmentQualityError(
                "Audio-to-lyrics match is insufficient for a reliable timeline"
            )
        aligned_moras = self._align_moras(
            targets,
            observations,
            matches,
            round(transcript.duration_seconds * 1000),
            line_windows,
        )
        confidence = match_ratio

        lines: list[AlignedLine] = []
        mora_offset = 0
        for line_index, lyric_line in enumerate(lyrics.lines):
            tokens: list[AlignedToken] = []
            for token_index, lyric_token in enumerate(lyric_line.tokens):
                count = sum(
                    target.line_index == line_index
                    and target.token_index == token_index
                    for target in targets
                )
                token_moras = aligned_moras[mora_offset : mora_offset + count]
                mora_offset += count
                if token_moras:
                    start_ms = token_moras[0].start_ms
                    end_ms = token_moras[-1].end_ms
                    token_confidence = self._confidence(token_moras)
                else:
                    anchor_ms = (
                        tokens[-1].end_ms
                        if tokens
                        else (
                            aligned_moras[mora_offset].start_ms
                            if mora_offset < len(aligned_moras)
                            else 0
                        )
                    )
                    start_ms = anchor_ms
                    end_ms = anchor_ms
                    token_confidence = 1.0
                tokens.append(
                    AlignedToken(
                        surface=lyric_token.surface,
                        reading=lyric_token.reading,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        confidence=token_confidence,
                        moras=token_moras,
                    )
                )
            lines.append(
                AlignedLine(
                    surface=lyric_line.surface,
                    reading=lyric_line.reading,
                    start_ms=tokens[0].start_ms,
                    end_ms=tokens[-1].end_ms,
                    confidence=sum(token.confidence for token in tokens) / len(tokens),
                    tokens=tokens,
                )
            )

        warnings = [] if confidence == 1.0 else ["partial_alignment"]
        return LyricTimeline(
            confidence=confidence,
            lines=lines,
            warnings=warnings,
            alignment_engine="whisper_mora",
        )

    @staticmethod
    def _lyric_moras(lyrics: LyricDocument) -> list[_TargetMora]:
        return [
            _TargetMora(line_index, token_index, mora)
            for line_index, line in enumerate(lyrics.lines)
            for token_index, token in enumerate(line.tokens)
            for mora in split_moras(normalize_reading(token.reading))
        ]

    @staticmethod
    def _transcript_moras(transcript: TranscriptDocument) -> list[_TimedMora]:
        result: list[_TimedMora] = []
        for segment in transcript.segments:
            for word in segment.words:
                moras = split_moras(normalize_reading(word.text))
                if not moras:
                    continue
                duration = word.end_ms - word.start_ms
                for index, mora in enumerate(moras):
                    raw_start_ms = (
                        word.start_ms + duration * index // len(moras)
                    )
                    raw_end_ms = (
                        word.start_ms
                        + duration * (index + 1) // len(moras)
                    )
                    start_ms = max(
                        raw_start_ms,
                        result[-1].end_ms if result else raw_start_ms,
                    )
                    result.append(
                        _TimedMora(
                            reading=mora,
                            start_ms=start_ms,
                            end_ms=max(start_ms, raw_end_ms),
                        )
                    )
        return result

    @staticmethod
    def _matches(
        targets: list[_TargetMora],
        observations: list[_TimedMora],
        line_windows: dict[int, tuple[int, int]],
    ) -> dict[int, int]:
        matches: dict[int, int] = {}
        line_indexes = sorted({target.line_index for target in targets})
        for line_index in line_indexes:
            line_target_indexes = [
                index
                for index, target in enumerate(targets)
                if target.line_index == line_index
            ]
            if not line_target_indexes or line_index not in line_windows:
                continue
            readings = [
                targets[index].reading for index in line_target_indexes
            ]
            window_start, window_end = line_windows[line_index]
            observation_indexes = [
                index
                for index, observation in enumerate(observations)
                if window_start
                <= (observation.start_ms + observation.end_ms) // 2
                <= window_end
            ]
            if not observation_indexes:
                continue
            matcher = SequenceMatcher(
                None,
                readings,
                [
                    observations[index].reading
                    for index in observation_indexes
                ],
                autojunk=False,
            )
            for block in matcher.get_matching_blocks():
                for offset in range(block.size):
                    matches[line_target_indexes[block.a + offset]] = (
                        observation_indexes[block.b + offset]
                    )
        return matches

    @staticmethod
    def _line_windows(
        lyrics: LyricDocument,
        transcript: TranscriptDocument,
    ) -> dict[int, tuple[int, int]]:
        lyric_readings = [
            normalize_reading(line.reading) for line in lyrics.lines
        ]
        segment_readings = [
            normalize_reading(
                "".join(word.text for word in segment.words)
                or segment.text
            )
            for segment in transcript.segments
        ]
        line_count = len(lyric_readings)
        segment_count = len(segment_readings)
        negative_infinity = float("-inf")
        scores = [
            [negative_infinity] * (segment_count + 1)
            for _ in range(line_count + 1)
        ]
        actions: list[list[str | None]] = [
            [None] * (segment_count + 1)
            for _ in range(line_count + 1)
        ]
        scores[0][0] = 0.0
        for line_index in range(1, line_count + 1):
            scores[line_index][0] = scores[line_index - 1][0] - 0.35
            actions[line_index][0] = "skip_line"
        for segment_index in range(1, segment_count + 1):
            scores[0][segment_index] = (
                scores[0][segment_index - 1] - 0.15
            )
            actions[0][segment_index] = "skip_segment"

        def similarity(left: str, right: str) -> float:
            return SequenceMatcher(
                None,
                split_moras(left),
                split_moras(right),
                autojunk=False,
            ).ratio()

        def match_score(left: str, right: str) -> float:
            return similarity(left, right) * 2 - 0.8

        for line_index in range(1, line_count + 1):
            for segment_index in range(1, segment_count + 1):
                choices = [
                    (
                        scores[line_index - 1][segment_index] - 0.35,
                        "skip_line",
                    ),
                    (
                        scores[line_index][segment_index - 1] - 0.15,
                        "skip_segment",
                    ),
                    (
                        scores[line_index - 1][segment_index - 1]
                        + match_score(
                            lyric_readings[line_index - 1],
                            segment_readings[segment_index - 1],
                        ),
                        "match_1_1",
                    ),
                ]
                if segment_index >= 2:
                    choices.append(
                        (
                            scores[line_index - 1][segment_index - 2]
                            + match_score(
                                lyric_readings[line_index - 1],
                                segment_readings[segment_index - 2]
                                + segment_readings[segment_index - 1],
                            )
                            - 0.05,
                            "match_1_2",
                        )
                    )
                if line_index >= 2:
                    choices.append(
                        (
                            scores[line_index - 2][segment_index - 1]
                            + match_score(
                                lyric_readings[line_index - 2]
                                + lyric_readings[line_index - 1],
                                segment_readings[segment_index - 1],
                            )
                            - 0.05,
                            "match_2_1",
                        )
                    )
                score, action = max(choices, key=lambda choice: choice[0])
                scores[line_index][segment_index] = score
                actions[line_index][segment_index] = action

        windows: dict[int, tuple[int, int]] = {}
        line_index = line_count
        # Transcript material after the last supplied lyric line may be an
        # instrumental outro, speech, or a repeated phrase.  Treat that suffix
        # as free instead of forcing the alignment to consume it; otherwise a
        # later exact repeat can beat the nearby, slightly imperfect singing.
        segment_index = max(
            range(segment_count + 1),
            key=lambda candidate: scores[line_count][candidate],
        )
        while line_index > 0 or segment_index > 0:
            action = actions[line_index][segment_index]
            if action == "skip_line":
                line_index -= 1
            elif action == "skip_segment":
                segment_index -= 1
            elif action == "match_1_1":
                segment = transcript.segments[segment_index - 1]
                windows[line_index - 1] = (
                    segment.start_ms,
                    segment.end_ms,
                )
                line_index -= 1
                segment_index -= 1
            elif action == "match_1_2":
                windows[line_index - 1] = (
                    transcript.segments[segment_index - 2].start_ms,
                    transcript.segments[segment_index - 1].end_ms,
                )
                line_index -= 1
                segment_index -= 2
            elif action == "match_2_1":
                segment = transcript.segments[segment_index - 1]
                first_length = max(
                    1,
                    len(split_moras(lyric_readings[line_index - 2])),
                )
                second_length = max(
                    1,
                    len(split_moras(lyric_readings[line_index - 1])),
                )
                split_ms = segment.start_ms + (
                    (segment.end_ms - segment.start_ms)
                    * first_length
                    // (first_length + second_length)
                )
                windows[line_index - 2] = (
                    segment.start_ms,
                    split_ms,
                )
                windows[line_index - 1] = (
                    split_ms,
                    segment.end_ms,
                )
                line_index -= 2
                segment_index -= 1
            else:
                break
        return windows

    @staticmethod
    def _complete_line_windows(
        lyrics: LyricDocument,
        windows: dict[int, tuple[int, int]],
        observations: list[_TimedMora],
    ) -> dict[int, tuple[int, int]]:
        if not windows:
            raise AlignmentQualityError(
                "ASR text did not match any lyric lines"
            )
        completed = dict(windows)
        line_count = len(lyrics.lines)
        index = 0
        while index < line_count:
            if index in completed:
                index += 1
                continue
            gap_start = index
            while index < line_count and index not in completed:
                index += 1
            gap_end = index
            previous_end = (
                completed[gap_start - 1][1]
                if gap_start > 0 and gap_start - 1 in completed
                else observations[0].start_ms
            )
            next_start = (
                completed[gap_end][0]
                if gap_end < line_count and gap_end in completed
                else observations[-1].end_ms
            )
            lengths = [
                max(
                    1,
                    len(
                        split_moras(
                            normalize_reading(lyrics.lines[line].reading)
                        )
                    ),
                )
                for line in range(gap_start, gap_end)
            ]
            total_mora_count = sum(lengths)
            span = max(0, next_start - previous_end)
            median_duration = LyricTimelineAligner._median_mora_duration(
                observations
            )
            estimated_total = total_mora_count * median_duration
            scale = span / max(1, estimated_total)
            elapsed = previous_end
            for offset, line in enumerate(range(gap_start, gap_end)):
                line_duration = round(lengths[offset] * median_duration * scale)
                end_ms = min(elapsed + line_duration, next_start)
                completed[line] = (elapsed, end_ms)
                elapsed = end_ms
        return completed

    @staticmethod
    def _median_mora_duration(observations: list[_TimedMora]) -> int:
        durations = sorted(
            o.end_ms - o.start_ms
            for o in observations
            if o.end_ms > o.start_ms
        )
        return durations[len(durations) // 2] if durations else 200

    @staticmethod
    def _align_moras(
        targets: list[_TargetMora],
        observations: list[_TimedMora],
        matches: dict[int, int],
        duration_ms: int,
        line_windows: dict[int, tuple[int, int]],
    ) -> list[AlignedMora]:
        aligned: list[AlignedMora | None] = [None] * len(targets)
        for target_index, observation_index in matches.items():
            observation = observations[observation_index]
            aligned[target_index] = AlignedMora(
                reading=targets[target_index].reading,
                start_ms=observation.start_ms,
                end_ms=observation.end_ms,
                matched=True,
                confidence=1.0,
            )

        default_duration = LyricTimelineAligner._default_mora_duration(observations)
        for line_index in sorted({target.line_index for target in targets}):
            indexes = [
                index
                for index, target in enumerate(targets)
                if target.line_index == line_index
            ]
            if not indexes:
                continue
            window_start, window_end = line_windows.get(
                line_index,
                (
                    aligned[indexes[0]].start_ms
                    if aligned[indexes[0]] is not None
                    else 0,
                    aligned[indexes[-1]].end_ms
                    if aligned[indexes[-1]] is not None
                    else duration_ms,
                ),
            )
            position = 0
            while position < len(indexes):
                target_index = indexes[position]
                if aligned[target_index] is not None:
                    position += 1
                    continue
                gap_start_position = position
                while (
                    position < len(indexes)
                    and aligned[indexes[position]] is None
                ):
                    position += 1
                gap_end_position = position
                count = gap_end_position - gap_start_position
                previous = (
                    aligned[indexes[gap_start_position - 1]]
                    if gap_start_position
                    else None
                )
                following = (
                    aligned[indexes[gap_end_position]]
                    if gap_end_position < len(indexes)
                    else None
                )

                if previous is not None and following is not None:
                    start_ms = previous.end_ms
                    end_ms = max(start_ms, following.start_ms)
                elif following is not None:
                    end_ms = following.start_ms
                    start_ms = max(
                        window_start,
                        end_ms - default_duration * count,
                    )
                elif previous is not None:
                    start_ms = previous.end_ms
                    end_ms = max(start_ms, window_end)
                else:
                    start_ms = window_start
                    end_ms = max(
                        start_ms,
                        min(duration_ms, window_end),
                    )

                span = end_ms - start_ms
                for offset, local_position in enumerate(
                    range(gap_start_position, gap_end_position)
                ):
                    index = indexes[local_position]
                    aligned[index] = AlignedMora(
                        reading=targets[index].reading,
                        start_ms=start_ms + span * offset // count,
                        end_ms=start_ms + span * (offset + 1) // count,
                        matched=False,
                        confidence=0.0,
                    )

        ordered = [mora for mora in aligned if mora is not None]
        normalized: list[AlignedMora] = []
        for mora in ordered:
            start_ms = max(
                mora.start_ms,
                normalized[-1].end_ms if normalized else mora.start_ms,
            )
            normalized.append(
                AlignedMora(
                    reading=mora.reading,
                    start_ms=start_ms,
                    end_ms=max(start_ms, mora.end_ms),
                    matched=mora.matched,
                    confidence=mora.confidence,
                )
            )
        return normalized

    @staticmethod
    def _default_mora_duration(observations: list[_TimedMora]) -> int:
        durations = sorted(
            observation.end_ms - observation.start_ms
            for observation in observations
            if observation.end_ms > observation.start_ms
        )
        return durations[len(durations) // 2] if durations else 200

    @staticmethod
    def _confidence(moras: list[AlignedMora]) -> float:
        return (
            sum(1 for mora in moras if mora.matched) / len(moras)
            if moras
            else 0.0
        )
