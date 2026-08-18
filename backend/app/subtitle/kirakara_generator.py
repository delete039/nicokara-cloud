from __future__ import annotations

from dataclasses import dataclass
import re

from app.alignment.models import AlignedLine, LyricTimeline
from app.subtitle.karaoke_effect import (
    KaraokeChunk,
    escape_ass_text,
    is_sung_text,
    line_chunks,
    ruby_chunks,
    ruby_start_ms,
)
from app.subtitle.font_metrics import text_ink_measurer, text_measurer
from app.subtitle.ruby import kanji_readings


_UNSAFE_FONT_NAME = re.compile(r"[,;\r\n{}\[\]'\"]")


@dataclass(frozen=True)
class _CharacterLayout:
    text: str
    x: int
    ink_left: float
    ink_right: float


@dataclass(frozen=True)
class _RubyLayout:
    text: str
    character_x: tuple[int, ...]
    character_ink: tuple[tuple[float, float], ...]
    y: int
    token_index: int


@dataclass(frozen=True)
class _LineLayout:
    characters: tuple[_CharacterLayout, ...]
    ruby: tuple[_RubyLayout, ...]
    y: int


@dataclass(frozen=True)
class _LineTiming:
    paragraph: int
    line_in_paragraph: int
    display_start_ms: int
    display_end_ms: int
    is_first_in_paragraph: bool
    is_last_in_paragraph: bool


@dataclass(frozen=True)
class KirakaraAssConfig:
    play_res_x: int = 1920
    play_res_y: int = 1080
    font_name: str = "Noto Sans CJK JP"
    base_font_size: int = 96
    ruby_font_size: int = 39
    upper_left_x: int = 192
    upper_y: int = 645
    lower_right_x: int = 1728
    lower_y: int = 845
    entry_buffer_ms: int = 4166
    exit_hold_ms: int = 2000
    fade_duration_ms: int = 666
    walk_protect_ms: int = 1000
    walk_protect_margin_ms: int = 2500
    indicator_duration_ms: int = 3000
    indicator_size: int = 51
    indicator_spacing: int = 18
    indicator_stroke_width: float = 4.5
    indicator_offset_x: int = 0
    indicator_offset_y: int = 12
    ruby_offset: int = 6
    sung_color: str = "&H000000A5"
    unsung_color: str = "&H00FFFFFF"
    outline_width: int = 8
    ruby_outline_width: int = 6
    base_letter_spacing: int = 14
    ruby_letter_spacing: int = 8

    @classmethod
    def from_browser_style(cls, value: object) -> "KirakaraAssConfig":
        if not isinstance(value, dict):
            return cls()

        def number(key: str, default: int, minimum: int, maximum: int) -> int:
            try:
                parsed = round(float(value.get(key, default)))
            except (TypeError, ValueError):
                return default
            return min(maximum, max(minimum, parsed))

        def ass_color(key: str, default: str) -> str:
            raw = value.get(key)
            if not isinstance(raw, str) or len(raw) != 7 or raw[0] != "#":
                return default
            try:
                red, green, blue = raw[1:3], raw[3:5], raw[5:7]
                int(red + green + blue, 16)
            except ValueError:
                return default
            return f"&H00{blue}{green}{red}".upper()

        font_name = str(value.get("font_family") or cls.font_name).strip()
        if (
            len(font_name) >= 2
            and font_name[0] in {"'", '"'}
            and font_name[-1] == font_name[0]
        ):
            font_name = font_name[1:-1].strip()
        if (
            not font_name
            or len(font_name) > 100
            or _UNSAFE_FONT_NAME.search(font_name)
        ):
            font_name = cls.font_name
        def scaled(number: int | float) -> int:
            # JavaScript Math.round semantics used by the browser renderer.
            return int(float(number) * 1.5 + 0.5)

        font_size = number("font_size", 64, 48, 80)
        ruby_size = number("ruby_size", 26, 18, 38)
        stroke_width = number("stroke_width", 5, 2, 8)
        return cls(
            font_name=font_name,
            base_font_size=scaled(font_size),
            ruby_font_size=scaled(ruby_size),
            upper_y=scaled(number("upper_y", 430, 320, 560)),
            lower_y=scaled(number("lower_y", 563, 440, 680)),
            sung_color=ass_color("color_after", cls.sung_color),
            unsung_color=ass_color("color_before", cls.unsung_color),
            outline_width=scaled(stroke_width),
            ruby_outline_width=max(1, scaled(stroke_width * 0.8)),
        )


def ass_time(milliseconds: int) -> str:
    centiseconds = max(0, round(milliseconds / 10))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


class KirakaraAssGenerator:
    """Generate the same alternating two-slot profile as browser Kirakara."""

    def __init__(self, *, config: KirakaraAssConfig | None = None) -> None:
        self.config = config or KirakaraAssConfig()

    def generate(self, timeline: LyricTimeline) -> str:
        events: list[str] = []
        timings = self._line_timings(timeline.lines)
        for line, timing in zip(timeline.lines, timings, strict=True):
            display_start = ass_time(timing.display_start_ms)
            display_end = ass_time(timing.display_end_ms)
            layout = self._layout_line(line, timing.line_in_paragraph)
            if timing.line_in_paragraph == 0:
                events.extend(
                    self._indicator_events(
                        line,
                        timing.display_start_ms,
                    )
                )
            events.extend(
                self._base_events(
                    layout,
                    display_start,
                    display_end,
                    fade_in=timing.is_first_in_paragraph,
                    fade_out=timing.is_last_in_paragraph,
                )
            )
            events.extend(
                self._ruby_events(
                    layout,
                    display_start,
                    display_end,
                    fade_in=timing.is_first_in_paragraph,
                    fade_out=timing.is_last_in_paragraph,
                )
            )
            events.extend(
                self._ruby_progress_events(
                    line,
                    layout,
                    timing.display_end_ms,
                    fade_out=timing.is_last_in_paragraph,
                )
            )
            events.extend(
                self._main_progress_events(
                    line,
                    layout,
                    timing.display_end_ms,
                    fade_out=timing.is_last_in_paragraph,
                )
            )
        return self._header() + "\n" + "\n".join(events) + "\n"

    def _line_timings(
        self,
        lines: list[AlignedLine],
    ) -> list[_LineTiming]:
        if not lines:
            return []

        paragraph = 0
        line_in_paragraph = 0
        paragraph_start_ms = lines[0].start_ms
        raw: list[dict[str, int]] = []
        for index, line in enumerate(lines):
            previous = lines[index - 1] if index > 0 else None
            if (
                previous is not None
                and line.start_ms - previous.end_ms
                > self.config.entry_buffer_ms + self.config.exit_hold_ms
            ):
                paragraph += 1
                line_in_paragraph = 0
                paragraph_start_ms = line.start_ms
            entry_ms = line.start_ms - self.config.entry_buffer_ms
            if line_in_paragraph == 1:
                entry_ms = paragraph_start_ms - self.config.entry_buffer_ms
            raw.append(
                {
                    "paragraph": paragraph,
                    "line_in_paragraph": line_in_paragraph,
                    "entry_ms": entry_ms,
                    "walk_done_ms": line.end_ms,
                }
            )
            line_in_paragraph += 1

        # This mirrors Kirakara parser.js:370-390. Same-slot lines are two
        # indices apart while they stay inside one paragraph.
        for index in range(max(0, len(raw) - 2)):
            current = raw[index]
            next_in_slot = raw[index + 2]
            if next_in_slot["paragraph"] != current["paragraph"]:
                continue
            if (
                next_in_slot["entry_ms"]
                > lines[index].end_ms + self.config.exit_hold_ms
            ):
                current["walk_done_ms"] = (
                    lines[index].end_ms + self.config.exit_hold_ms
                )
                next_in_slot["entry_ms"] = current["walk_done_ms"]

        for index in range(max(0, len(raw) - 2)):
            current = raw[index]
            next_in_slot = raw[index + 2]
            if next_in_slot["paragraph"] != current["paragraph"]:
                continue
            proposed = current["walk_done_ms"] + self.config.walk_protect_ms
            if (
                lines[index + 2].start_ms
                >= proposed + self.config.walk_protect_margin_ms
            ):
                current["walk_done_ms"] = proposed

        display_starts: list[int] = []
        for index, value in enumerate(raw):
            display_start = value["entry_ms"]
            if index >= 2 and raw[index - 2]["paragraph"] == value["paragraph"]:
                display_start = max(
                    display_start,
                    raw[index - 2]["walk_done_ms"],
                )
            display_starts.append(max(0, display_start))

        timings: list[_LineTiming] = []
        for index, value in enumerate(raw):
            natural_end = lines[index].end_ms + self.config.exit_hold_ms
            display_end = natural_end
            slot = value["line_in_paragraph"] % 2
            for next_index in range(index + 1, len(raw)):
                if raw[next_index]["line_in_paragraph"] % 2 != slot:
                    continue
                display_end = min(display_end, display_starts[next_index])
                break
            display_end = max(display_starts[index], display_end)
            next_value = raw[index + 1] if index + 1 < len(raw) else None
            timings.append(
                _LineTiming(
                    paragraph=value["paragraph"],
                    line_in_paragraph=value["line_in_paragraph"],
                    display_start_ms=display_starts[index],
                    display_end_ms=display_end,
                    is_first_in_paragraph=value["line_in_paragraph"] <= 1,
                    is_last_in_paragraph=(
                        next_value is None
                        or next_value["paragraph"] != value["paragraph"]
                    ),
                )
            )
        return timings

    def _line_y(self, index: int) -> int:
        return self.config.upper_y if index % 2 == 0 else self.config.lower_y

    def _position_tags(
        self,
        x: int,
        y: int,
        *,
        alignment: int,
        fade_in: bool = False,
        fade_out: bool = False,
    ) -> str:
        tags = rf"\an{alignment}\pos({x},{y})"
        if fade_in or fade_out:
            tags += (
                rf"\fad({self.config.fade_duration_ms if fade_in else 0},"
                rf"{self.config.fade_duration_ms if fade_out else 0})"
            )
        return tags

    @staticmethod
    def _text_width(
        text: str,
        measure,
        spacing: int,
    ) -> float:
        return sum(measure(character) for character in text) + max(
            0,
            len(text) - 1,
        ) * spacing

    def _layout_line(self, line: AlignedLine, index: int) -> _LineLayout:
        base_measure = text_measurer(
            self.config.font_name,
            self.config.base_font_size,
            bold=True,
        )
        ruby_measure = text_measurer(
            self.config.font_name,
            self.config.ruby_font_size,
        )
        base_ink_measure = text_ink_measurer(
            self.config.font_name,
            self.config.base_font_size,
            bold=True,
        )
        ruby_ink_measure = text_ink_measurer(
            self.config.font_name,
            self.config.ruby_font_size,
        )

        ruby_runs: dict[int, tuple[int, str, int]] = {}
        token_offset = 0
        for token_index, token in enumerate(line.tokens):
            if not line.surface.startswith(token.surface, token_offset):
                found_at = line.surface.find(token.surface, token_offset)
                if found_at < 0:
                    continue
                token_offset = found_at
            for run_start, run_end, reading in kanji_readings(
                token.surface,
                token.reading,
            ):
                if reading:
                    ruby_runs[token_offset + run_start] = (
                        token_offset + run_end,
                        reading,
                        token_index,
                    )
            token_offset += len(token.surface)

        groups: list[tuple[int, int, str | None, int | None]] = []
        character_index = 0
        while character_index < len(line.surface):
            ruby_run = ruby_runs.get(character_index)
            if ruby_run is not None and ruby_run[0] <= len(line.surface):
                end, reading, token_index = ruby_run
                groups.append((character_index, end, reading, token_index))
                character_index = end
                continue
            groups.append((character_index, character_index + 1, None, None))
            character_index += 1

        group_layouts: list[tuple[str, str | None, int | None, float, float]] = []
        total_width = 0.0
        for start, end, reading, token_index in groups:
            surface = line.surface[start:end]
            base_width = self._text_width(
                surface,
                base_measure,
                self.config.base_letter_spacing,
            )
            ruby_width = (
                self._text_width(
                    reading,
                    ruby_measure,
                    self.config.ruby_letter_spacing,
                )
                if reading
                else 0.0
            )
            effective_width = max(base_width, ruby_width)
            group_layouts.append(
                (surface, reading, token_index, base_width, effective_width)
            )
            total_width += effective_width
        total_width += max(0, len(group_layouts) - 1) * self.config.base_letter_spacing

        cursor = (
            float(self.config.upper_left_x)
            if index % 2 == 0
            else float(self.config.lower_right_x) - total_width
        )
        characters: list[_CharacterLayout] = []
        ruby_layouts: list[_RubyLayout] = []
        ruby_y = (
            self._line_y(index)
            - self.config.ruby_font_size
            - self.config.ruby_offset
        )
        for surface, reading, token_index, base_width, effective_width in group_layouts:
            main_cursor = cursor + (effective_width - base_width) / 2
            for character in surface:
                ink_left, ink_right = base_ink_measure(character)
                characters.append(
                    _CharacterLayout(
                        text=character,
                        x=round(main_cursor),
                        ink_left=ink_left,
                        ink_right=ink_right,
                    )
                )
                main_cursor += base_measure(character) + self.config.base_letter_spacing

            if reading is not None and token_index is not None:
                ruby_width = self._text_width(
                    reading,
                    ruby_measure,
                    self.config.ruby_letter_spacing,
                )
                ruby_cursor = cursor + (effective_width - ruby_width) / 2
                ruby_character_x: list[int] = []
                ruby_character_ink: list[tuple[float, float]] = []
                for character in reading:
                    ruby_character_x.append(round(ruby_cursor))
                    ruby_character_ink.append(ruby_ink_measure(character))
                    ruby_cursor += ruby_measure(character) + self.config.ruby_letter_spacing
                ruby_layouts.append(
                    _RubyLayout(
                        text=reading,
                        character_x=tuple(ruby_character_x),
                        character_ink=tuple(ruby_character_ink),
                        y=ruby_y,
                        token_index=token_index,
                    )
                )
            cursor += effective_width + self.config.base_letter_spacing

        return _LineLayout(
            characters=tuple(characters),
            ruby=tuple(ruby_layouts),
            y=self._line_y(index),
        )

    def _indicator_events(
        self,
        line: AlignedLine,
        display_start_ms: int,
    ) -> list[str]:
        config = self.config
        quarter_ms = config.indicator_duration_ms // 4
        top = (
            config.upper_y
            - config.ruby_font_size
            - config.ruby_offset
            - config.indicator_offset_y
            - config.indicator_size
        )
        radius = round(config.indicator_size / 2)
        control = round(radius * 0.55228475)
        size = config.indicator_size
        circle = (
            f"m {radius} 0 "
            f"b {radius + control} 0 {size} {radius - control} {size} {radius} "
            f"b {size} {radius + control} {radius + control} {size} {radius} {size} "
            f"b {radius - control} {size} 0 {radius + control} 0 {radius} "
            f"b 0 {radius - control} {radius - control} 0 {radius} 0"
        )
        events: list[str] = []
        for sequence_index in range(4):
            disappear_ms = (
                line.start_ms
                - config.indicator_duration_ms
                + sequence_index * quarter_ms
            )
            if disappear_ms <= display_start_ms:
                continue
            visual_index = 3 - sequence_index
            x = (
                config.upper_left_x
                + config.indicator_offset_x
                + visual_index
                * (config.indicator_size + config.indicator_spacing)
            )
            events.append(
                self._dialogue(
                    0,
                    ass_time(display_start_ms),
                    ass_time(disappear_ms),
                    "KirakaraIndicator",
                    rf"\an7\pos({x},{top})\p1",
                    circle,
                )
            )
        return events

    def _progress_tags(
        self,
        *,
        x: int,
        y: int,
        duration_ms: int,
        ink_left: float,
        ink_right: float,
        stroke_width: int,
    ) -> str:
        """Animate the complete sung layer with Kirakara's ink-aware clip."""
        clip_left = round(x - stroke_width - ink_left - 1)
        clip_right = round(x + ink_right + stroke_width + 1)
        top = 0
        bottom = self.config.play_res_y
        return (
            self._position_tags(x, y, alignment=7)
            + rf"\clip({clip_left},{top},{clip_left},{bottom})"
            + rf"\t(0,{duration_ms},\clip({clip_left},{top},{clip_right},{bottom}))"
        )

    def _base_events(
        self,
        layout: _LineLayout,
        start: str,
        end: str,
        *,
        fade_in: bool,
        fade_out: bool,
    ) -> list[str]:
        return [
            self._dialogue(
                1,
                start,
                end,
                "KirakaraBase",
                self._position_tags(
                    character.x,
                    layout.y,
                    alignment=7,
                    fade_in=fade_in,
                    fade_out=fade_out,
                ),
                escape_ass_text(character.text),
            )
            for character in layout.characters
        ]

    def _ruby_events(
        self,
        layout: _LineLayout,
        start: str,
        end: str,
        *,
        fade_in: bool,
        fade_out: bool,
    ) -> list[str]:
        events: list[str] = []
        for ruby in layout.ruby:
            events.extend(
                self._dialogue(
                    2,
                    start,
                    end,
                    "KirakaraRuby",
                    self._position_tags(
                        x,
                        ruby.y,
                        alignment=7,
                        fade_in=fade_in,
                        fade_out=fade_out,
                    ),
                    escape_ass_text(character),
                )
                for character, x in zip(
                    ruby.text,
                    ruby.character_x,
                    strict=True,
                )
            )
        return events

    def _ruby_progress_events(
        self,
        line: AlignedLine,
        layout: _LineLayout,
        display_end_ms: int,
        *,
        fade_out: bool,
    ) -> list[str]:
        events: list[str] = []
        for ruby in layout.ruby:
            token = line.tokens[ruby.token_index]
            chunks = ruby_chunks(token, ruby.text)
            if len(chunks) != len(ruby.character_x):
                continue
            current_ms = ruby_start_ms(token, ruby.text)
            for chunk, x, (ink_left, ink_right) in zip(
                chunks,
                ruby.character_x,
                ruby.character_ink,
                strict=True,
            ):
                duration_ms = max(0, chunk.duration_cs * 10)
                character_end_ms = current_ms + duration_ms
                if duration_ms > 0 and is_sung_text(chunk.text):
                    events.append(
                        self._dialogue(
                            4,
                            ass_time(current_ms),
                            ass_time(character_end_ms),
                            "KirakaraRubyProgress",
                            self._progress_tags(
                                x=x,
                                y=ruby.y,
                                duration_ms=duration_ms,
                                ink_left=ink_left,
                                ink_right=ink_right,
                                stroke_width=self.config.ruby_outline_width,
                            ),
                            escape_ass_text(chunk.text),
                        )
                    )
                    if character_end_ms < display_end_ms:
                        events.append(
                            self._dialogue(
                                6,
                                ass_time(character_end_ms),
                                ass_time(display_end_ms),
                                "KirakaraRubySung",
                                self._position_tags(
                                    x,
                                    ruby.y,
                                    alignment=7,
                                    fade_out=fade_out,
                                ),
                                escape_ass_text(chunk.text),
                            )
                        )
                current_ms = character_end_ms
        return events

    def _main_progress_events(
        self,
        line: AlignedLine,
        layout: _LineLayout,
        display_end_ms: int,
        *,
        fade_out: bool,
    ) -> list[str]:
        chunks = line_chunks(line)
        if (
            len(chunks) != len(layout.characters)
            or "".join(chunk.text for chunk in chunks) != line.surface
        ):
            chunks = self._uniform_line_chunks(line)

        events: list[str] = []
        current_ms = line.start_ms
        for chunk, character in zip(chunks, layout.characters, strict=True):
            duration_ms = max(0, chunk.duration_cs * 10)
            character_end_ms = current_ms + duration_ms
            if duration_ms > 0 and is_sung_text(chunk.text):
                events.append(
                    self._dialogue(
                        3,
                        ass_time(current_ms),
                        ass_time(character_end_ms),
                        "KirakaraProgress",
                        self._progress_tags(
                            x=character.x,
                            y=layout.y,
                            duration_ms=duration_ms,
                            ink_left=character.ink_left,
                            ink_right=character.ink_right,
                            stroke_width=self.config.outline_width,
                        ),
                        escape_ass_text(chunk.text),
                    )
                )
                if character_end_ms < display_end_ms:
                    events.append(
                        self._dialogue(
                            5,
                            ass_time(character_end_ms),
                            ass_time(display_end_ms),
                            "KirakaraSung",
                            self._position_tags(
                                character.x,
                                layout.y,
                                alignment=7,
                                fade_out=fade_out,
                            ),
                            escape_ass_text(chunk.text),
                        )
                    )
            current_ms = character_end_ms
        return events

    @staticmethod
    def _uniform_line_chunks(line: AlignedLine) -> list[KaraokeChunk]:
        sung_indices = [
            index
            for index, character in enumerate(line.surface)
            if is_sung_text(character)
        ]
        durations = [0] * len(line.surface)
        if sung_indices:
            total_cs = max(0, round((line.end_ms - line.start_ms) / 10))
            base, remainder = divmod(total_cs, len(sung_indices))
            for position, index in enumerate(sung_indices):
                durations[index] = base + (
                    1 if position >= len(sung_indices) - remainder else 0
                )
        return [
            KaraokeChunk(text=character, duration_cs=durations[index])
            for index, character in enumerate(line.surface)
        ]

    @staticmethod
    def _dialogue(
        layer: int,
        start: str,
        end: str,
        style: str,
        tags: str,
        text: str,
    ) -> str:
        return (
            f"Dialogue: {layer},{start},{end},{style},,0,0,0,,"
            f"{{{tags}}}{text}"
        )

    def _header(self) -> str:
        config = self.config
        return f"""[Script Info]
Title: Nicokara Kirakara Render
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {config.play_res_x}
PlayResY: {config.play_res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: KirakaraIndicator,Arial,10,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{config.indicator_stroke_width},0,7,0,0,0,1
Style: KirakaraBase,{config.font_name},{config.base_font_size},{config.unsung_color},{config.unsung_color},&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{config.outline_width},0,7,0,0,0,1
Style: KirakaraRuby,{config.font_name},{config.ruby_font_size},{config.unsung_color},{config.unsung_color},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{config.ruby_outline_width},0,7,0,0,0,1
Style: KirakaraProgress,{config.font_name},{config.base_font_size},{config.sung_color},{config.sung_color},&H00FFFFFF,&H00000000,-1,0,0,0,100,100,0,0,1,{config.outline_width},0,7,0,0,0,1
Style: KirakaraRubyProgress,{config.font_name},{config.ruby_font_size},{config.sung_color},{config.sung_color},&H00FFFFFF,&H00000000,0,0,0,0,100,100,0,0,1,{config.ruby_outline_width},0,7,0,0,0,1
Style: KirakaraSung,{config.font_name},{config.base_font_size},{config.sung_color},{config.sung_color},&H00FFFFFF,&H00000000,-1,0,0,0,100,100,0,0,1,{config.outline_width},0,7,0,0,0,1
Style: KirakaraRubySung,{config.font_name},{config.ruby_font_size},{config.sung_color},{config.sung_color},&H00FFFFFF,&H00000000,0,0,0,0,100,100,0,0,1,{config.ruby_outline_width},0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""
