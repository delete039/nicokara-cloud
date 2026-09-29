from __future__ import annotations

from dataclasses import dataclass, replace
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
from app.subtitle.font_metrics import ass_font_geometry, text_ink_measurer, text_measurer
from app.subtitle.ruby import kanji_readings


_UNSAFE_FONT_NAME = re.compile(r"[,;\r\n{}\[\]'\"]")


@dataclass(frozen=True)
class _CharacterLayout:
    text: str
    x: float
    ink_left: float
    ink_right: float


@dataclass(frozen=True)
class _RubyLayout:
    text: str
    character_x: tuple[float, ...]
    character_ink: tuple[tuple[float, float], ...]
    y: float
    token_index: int


@dataclass(frozen=True)
class _RomajiCharacterLayout:
    text: str
    x: float
    ink_left: float
    ink_right: float
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class _RomajiLayout:
    characters: tuple[_RomajiCharacterLayout, ...]
    y: float


@dataclass(frozen=True)
class _LineLayout:
    characters: tuple[_CharacterLayout, ...]
    ruby: tuple[_RubyLayout, ...]
    romaji: tuple[_RomajiLayout, ...]
    y: float


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
    base_font_bold: bool = True
    ruby_font_size: int = 39
    romaji_font_size: int = 39
    upper_left_x: int = 192
    upper_y: int = 645
    lower_right_x: int = 1728
    lower_y: float = 844.5
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
    romaji_offset: int = 6
    sung_color: str = "&H000000A5"
    unsung_color: str = "&H00FFFFFF"
    unsung_outline_color: str = "&H00000000"
    sung_outline_color: str = "&H00FFFFFF"
    outline_width: float = 7.5
    ruby_outline_width: float = 6
    romaji_outline_width: float = 3
    shadow_color: str = "&H00000000"
    shadow_depth: int = 0
    base_letter_spacing: float = 13.5
    ruby_letter_spacing: float = 7.5
    romaji_letter_spacing: float = 7.5

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

        def boolean(key: str, default: bool) -> bool:
            raw = value.get(key)
            return raw if isinstance(raw, bool) else default

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
        def scaled(number: int | float) -> float:
            # Kirakara uses CSS/subpixel coordinates; rounding here accumulates
            # visible drift across long lines, especially with negative spacing.
            return float(number) * 1.5

        font_size = number("font_size", 64, 24, 120)
        ruby_size = number("ruby_size", 26, 10, 60)
        romaji_follows_ruby = boolean("romaji_follow_ruby", True)
        romaji_size = (
            ruby_size
            if romaji_follows_ruby
            else number("romaji_size", ruby_size, 10, 60)
        )
        ruby_offset = number("ruby_offset", 4, 0, 32)
        romaji_offset = (
            ruby_offset
            if romaji_follows_ruby
            else number("romaji_offset", ruby_offset, 0, 32)
        )
        ruby_letter_spacing = number("ruby_letter_spacing", 5, -2, 20)
        romaji_letter_spacing = (
            ruby_letter_spacing
            if romaji_follows_ruby
            else number(
                "romaji_letter_spacing",
                ruby_letter_spacing,
                -2,
                20,
            )
        )
        stroke_width = number("stroke_width", 5, 0, 12)
        horizontal_margin = scaled(number("horizontal_margin", 128, 0, 320))
        return cls(
            font_name=font_name,
            base_font_bold=boolean("font_bold", True),
            base_font_size=scaled(font_size),
            ruby_font_size=scaled(ruby_size),
            romaji_font_size=scaled(romaji_size),
            upper_left_x=horizontal_margin,
            upper_y=scaled(number("upper_y", 430, 120, 600)),
            lower_right_x=cls.play_res_x - horizontal_margin,
            lower_y=scaled(number("lower_y", 563, 240, 700)),
            ruby_offset=scaled(ruby_offset),
            romaji_offset=scaled(romaji_offset),
            sung_color=ass_color("color_after", cls.sung_color),
            unsung_color=ass_color("color_before", cls.unsung_color),
            unsung_outline_color=ass_color(
                "stroke_color_before", cls.unsung_outline_color
            ),
            sung_outline_color=ass_color(
                "stroke_color_after", cls.sung_outline_color
            ),
            outline_width=scaled(stroke_width),
            ruby_outline_width=scaled(int(stroke_width * 0.8 + 0.5)),
            romaji_outline_width=scaled(2),
            shadow_color=ass_color("shadow_color", cls.shadow_color),
            shadow_depth=scaled(number("shadow_depth", 0, 0, 12)),
            base_letter_spacing=scaled(number("letter_spacing", 9, -4, 32)),
            ruby_letter_spacing=scaled(ruby_letter_spacing),
            romaji_letter_spacing=scaled(romaji_letter_spacing),
        )


def ass_time(milliseconds: int) -> str:
    centiseconds = max(0, round(milliseconds / 10))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def _pack_label_lefts(
    labels: list[tuple[float, float]],
    gap: float,
) -> list[float]:
    """Keep annotation labels ordered without changing the base text layout."""
    if len(labels) <= 1:
        return [left for left, _width in labels]

    offsets: list[float] = []
    offset = 0.0
    for _left, width in labels:
        offsets.append(offset)
        offset += width + gap

    blocks: list[dict[str, float | int]] = []
    for index, (left, _width) in enumerate(labels):
        blocks.append({
            "start": index,
            "end": index,
            "weight": 1.0,
            "value": left - offsets[index],
        })
        while len(blocks) >= 2 and blocks[-2]["value"] > blocks[-1]["value"]:
            right = blocks.pop()
            left_block = blocks.pop()
            weight = float(left_block["weight"]) + float(right["weight"])
            blocks.append({
                "start": int(left_block["start"]),
                "end": int(right["end"]),
                "weight": weight,
                "value": (
                    float(left_block["value"]) * float(left_block["weight"])
                    + float(right["value"]) * float(right["weight"])
                ) / weight,
            })

    packed = [0.0] * len(labels)
    for block in blocks:
        for index in range(int(block["start"]), int(block["end"]) + 1):
            packed[index] = float(block["value"]) + offsets[index]
    return packed


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
                self._romaji_events(
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
                self._romaji_progress_events(
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
        tags = rf"\an{alignment}\pos({x:g},{y:g})"
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
            bold=self.config.base_font_bold,
        )
        ruby_measure = text_measurer(
            self.config.font_name,
            self.config.ruby_font_size,
        )
        base_ink_measure = text_ink_measurer(
            self.config.font_name,
            self.config.base_font_size,
            bold=self.config.base_font_bold,
        )
        ruby_ink_measure = text_ink_measurer(
            self.config.font_name,
            self.config.ruby_font_size,
        )
        romaji_measure = text_measurer(
            self.config.font_name,
            self.config.romaji_font_size,
            bold=True,
        )
        romaji_ink_measure = text_ink_measurer(
            self.config.font_name,
            self.config.romaji_font_size,
            bold=True,
        )

        ruby_runs: dict[int, tuple[int, str, int]] = {}
        token_indexes: list[int | None] = [None] * len(line.surface)
        token_offset = 0
        for token_index, token in enumerate(line.tokens):
            if not line.surface.startswith(token.surface, token_offset):
                found_at = line.surface.find(token.surface, token_offset)
                if found_at < 0:
                    continue
                token_offset = found_at
            token_end = min(len(line.surface), token_offset + len(token.surface))
            for surface_index in range(token_offset, token_end):
                token_indexes[surface_index] = token_index
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
            groups.append((
                character_index,
                character_index + 1,
                None,
                token_indexes[character_index],
            ))
            character_index += 1

        group_layouts: list[tuple[str, str | None, int | None, float]] = []
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
            group_layouts.append((surface, reading, token_index, base_width))
            total_width += base_width
        total_width += max(0, len(group_layouts) - 1) * self.config.base_letter_spacing

        cursor = (
            float(self.config.upper_left_x)
            if index % 2 == 0
            else float(self.config.lower_right_x) - total_width
        )
        characters: list[_CharacterLayout] = []
        ruby_layouts: list[_RubyLayout] = []
        ruby_widths: list[float] = []
        token_bounds: dict[int, tuple[float, float]] = {}
        ruby_y = (
            self._line_y(index)
            - self.config.ruby_font_size * 1.1
            - self.config.ruby_offset
            + ass_font_geometry(self.config.font_name).top_offset(
                self.config.ruby_font_size, 1.1
            )
        )
        for surface, reading, token_index, base_width in group_layouts:
            if token_index is not None:
                previous_bounds = token_bounds.get(token_index)
                token_bounds[token_index] = (
                    cursor if previous_bounds is None else previous_bounds[0],
                    cursor + base_width,
                )
            main_cursor = cursor
            for character in surface:
                ink_left, ink_right = base_ink_measure(character)
                characters.append(
                    _CharacterLayout(
                        text=character,
                        x=main_cursor,
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
                ruby_cursor = cursor + (base_width - ruby_width) / 2
                ruby_character_x: list[float] = []
                ruby_character_ink: list[tuple[float, float]] = []
                for character in reading:
                    ruby_character_x.append(ruby_cursor)
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
                ruby_widths.append(ruby_width)
            cursor += base_width + self.config.base_letter_spacing

        packed_ruby_lefts = _pack_label_lefts(
            [
                (layout.character_x[0], width)
                for layout, width in zip(ruby_layouts, ruby_widths, strict=True)
            ],
            self.config.ruby_letter_spacing,
        )
        ruby_layouts = [
            replace(
                layout,
                character_x=tuple(
                    x + packed_left - layout.character_x[0]
                    for x in layout.character_x
                ),
            )
            for layout, packed_left in zip(
                ruby_layouts,
                packed_ruby_lefts,
                strict=True,
            )
        ]

        line_top = self._line_y(index)
        romaji_above_y = (
            line_top
            - self.config.ruby_font_size * 1.1
            - self.config.ruby_offset
            - self.config.romaji_font_size * 1.1
            - self.config.romaji_offset
            + ass_font_geometry(self.config.font_name, True).top_offset(
                self.config.romaji_font_size, 1.1
            )
        )
        romaji_below_y = (
            line_top
            + self.config.base_font_size * 1.2
            + self.config.romaji_offset
            + ass_font_geometry(self.config.font_name, True).top_offset(
                self.config.romaji_font_size, 1.1
            )
        )
        romaji_layouts: list[_RomajiLayout] = []
        romaji_widths: list[float] = []
        for token_index, token in enumerate(line.tokens):
            bounds = token_bounds.get(token_index)
            if bounds is None or not any(token.romaji_moras):
                continue
            chunks = token.romaji_moras
            if len(token.moras) == len(chunks):
                timings = [
                    (mora.start_ms, mora.end_ms)
                    for mora in token.moras
                ]
            else:
                duration = max(0, token.end_ms - token.start_ms)
                timings = [
                    (
                        token.start_ms + duration * chunk_index // len(chunks),
                        token.start_ms + duration * (chunk_index + 1) // len(chunks),
                    )
                    for chunk_index in range(len(chunks))
                ]
            visible_chunks = [chunk for chunk in chunks if chunk]
            width = sum(romaji_measure(chunk) for chunk in visible_chunks)
            width += max(0, len(visible_chunks) - 1) * self.config.romaji_letter_spacing
            romaji_cursor = bounds[0] + (bounds[1] - bounds[0] - width) / 2
            romaji_characters: list[_RomajiCharacterLayout] = []
            visible_chunk_index = 0
            for chunk, (chunk_start, chunk_end) in zip(
                chunks,
                timings,
                strict=True,
            ):
                chunk_characters = list(chunk)
                if not chunk_characters:
                    continue
                prefix = ""
                for character_index, character in enumerate(chunk_characters):
                    ink_left, ink_right = romaji_ink_measure(character)
                    character_start = chunk_start + (
                        (chunk_end - chunk_start) * character_index
                        // len(chunk_characters)
                    )
                    character_end = chunk_start + (
                        (chunk_end - chunk_start) * (character_index + 1)
                        // len(chunk_characters)
                    )
                    romaji_characters.append(
                        _RomajiCharacterLayout(
                            text=character,
                            x=romaji_cursor + romaji_measure(prefix),
                            ink_left=ink_left,
                            ink_right=ink_right,
                            start_ms=character_start,
                            end_ms=character_end,
                        )
                    )
                    prefix += character
                visible_chunk_index += 1
                romaji_cursor += romaji_measure(chunk)
                if visible_chunk_index < len(visible_chunks):
                    romaji_cursor += self.config.romaji_letter_spacing
            romaji_layouts.append(
                _RomajiLayout(
                    characters=tuple(romaji_characters),
                    y=(
                        romaji_below_y
                        if token.romaji_position == "below"
                        else romaji_above_y
                    ),
                )
            )
            romaji_widths.append(width)

        romaji_indexes_by_y: dict[float, list[int]] = {}
        for layout_index, layout in enumerate(romaji_layouts):
            romaji_indexes_by_y.setdefault(layout.y, []).append(layout_index)
        for layout_indexes in romaji_indexes_by_y.values():
            packed_lefts = _pack_label_lefts(
                [
                    (
                        romaji_layouts[layout_index].characters[0].x,
                        romaji_widths[layout_index],
                    )
                    for layout_index in layout_indexes
                ],
                self.config.romaji_letter_spacing,
            )
            for layout_index, packed_left in zip(
                layout_indexes,
                packed_lefts,
                strict=True,
            ):
                layout = romaji_layouts[layout_index]
                shift = packed_left - layout.characters[0].x
                romaji_layouts[layout_index] = replace(
                    layout,
                    characters=tuple(
                        replace(character, x=character.x + shift)
                        for character in layout.characters
                    ),
                )

        return _LineLayout(
            characters=tuple(characters),
            ruby=tuple(ruby_layouts),
            romaji=tuple(romaji_layouts),
            y=self._line_y(index) + ass_font_geometry(
                self.config.font_name, self.config.base_font_bold
            ).top_offset(self.config.base_font_size, 1.2),
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
            - (
                config.romaji_font_size + config.romaji_offset
                if any(
                    token.romaji_moras and token.romaji_position != "below"
                    for token in line.tokens
                )
                else 0
            )
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

    def _romaji_events(
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
                2,
                start,
                end,
                "KirakaraRomaji",
                self._position_tags(
                    character.x,
                    romaji.y,
                    alignment=7,
                    fade_in=fade_in,
                    fade_out=fade_out,
                ),
                escape_ass_text(character.text),
            )
            for romaji in layout.romaji
            for character in romaji.characters
        ]

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

    def _romaji_progress_events(
        self,
        layout: _LineLayout,
        display_end_ms: int,
        *,
        fade_out: bool,
    ) -> list[str]:
        events: list[str] = []
        for romaji in layout.romaji:
            for character in romaji.characters:
                duration_ms = max(0, character.end_ms - character.start_ms)
                if duration_ms <= 0 or not is_sung_text(character.text):
                    continue
                events.append(
                    self._dialogue(
                        4,
                        ass_time(character.start_ms),
                        ass_time(character.end_ms),
                        "KirakaraRomajiProgress",
                        self._progress_tags(
                            x=character.x,
                            y=romaji.y,
                            duration_ms=duration_ms,
                            ink_left=character.ink_left,
                            ink_right=character.ink_right,
                            stroke_width=self.config.romaji_outline_width,
                        ),
                        escape_ass_text(character.text),
                    )
                )
                if character.end_ms < display_end_ms:
                    events.append(
                        self._dialogue(
                            6,
                            ass_time(character.end_ms),
                            ass_time(display_end_ms),
                            "KirakaraRomajiSung",
                            self._position_tags(
                                character.x,
                                romaji.y,
                                alignment=7,
                                fade_out=fade_out,
                            ),
                            escape_ass_text(character.text),
                        )
                    )
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
        base_geometry = ass_font_geometry(self.config.font_name, self.config.base_font_bold)
        ruby_geometry = ass_font_geometry(self.config.font_name)
        romaji_geometry = ass_font_geometry(self.config.font_name, True)
        config = replace(
            self.config,
            font_name=base_geometry.family,
            base_font_size=round(self.config.base_font_size * base_geometry.size_ratio, 4),
            ruby_font_size=round(self.config.ruby_font_size * ruby_geometry.size_ratio, 4),
            romaji_font_size=round(
                self.config.romaji_font_size * romaji_geometry.size_ratio,
                4,
            ),
            # Canvas stroke is centered and uses lineWidth = stroke * 2.2.
            outline_width=self.config.outline_width * 1.1,
            ruby_outline_width=self.config.ruby_outline_width * 1.1,
            romaji_outline_width=self.config.romaji_outline_width * 1.1,
        )
        base_bold = -1 if config.base_font_bold else 0
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
Style: KirakaraBase,{config.font_name},{config.base_font_size},{config.unsung_color},{config.unsung_color},{config.unsung_outline_color},{config.shadow_color},{base_bold},0,0,0,100,100,{config.base_letter_spacing},0,1,{config.outline_width},{config.shadow_depth},7,0,0,0,1
Style: KirakaraRuby,{config.font_name},{config.ruby_font_size},{config.unsung_color},{config.unsung_color},{config.unsung_outline_color},{config.shadow_color},0,0,0,0,100,100,{config.ruby_letter_spacing},0,1,{config.ruby_outline_width},{config.shadow_depth},7,0,0,0,1
Style: KirakaraRomaji,{config.font_name},{config.romaji_font_size},{config.unsung_color},{config.unsung_color},{config.unsung_outline_color},{config.shadow_color},-1,0,0,0,100,100,{config.romaji_letter_spacing},0,1,{config.romaji_outline_width},{config.shadow_depth},7,0,0,0,1
Style: KirakaraProgress,{config.font_name},{config.base_font_size},{config.sung_color},{config.sung_color},{config.sung_outline_color},{config.shadow_color},{base_bold},0,0,0,100,100,{config.base_letter_spacing},0,1,{config.outline_width},{config.shadow_depth},7,0,0,0,1
Style: KirakaraRubyProgress,{config.font_name},{config.ruby_font_size},{config.sung_color},{config.sung_color},{config.sung_outline_color},{config.shadow_color},0,0,0,0,100,100,{config.ruby_letter_spacing},0,1,{config.ruby_outline_width},{config.shadow_depth},7,0,0,0,1
Style: KirakaraRomajiProgress,{config.font_name},{config.romaji_font_size},{config.sung_color},{config.sung_color},{config.sung_outline_color},{config.shadow_color},-1,0,0,0,100,100,{config.romaji_letter_spacing},0,1,{config.romaji_outline_width},{config.shadow_depth},7,0,0,0,1
Style: KirakaraSung,{config.font_name},{config.base_font_size},{config.sung_color},{config.sung_color},{config.sung_outline_color},{config.shadow_color},{base_bold},0,0,0,100,100,{config.base_letter_spacing},0,1,{config.outline_width},{config.shadow_depth},7,0,0,0,1
Style: KirakaraRubySung,{config.font_name},{config.ruby_font_size},{config.sung_color},{config.sung_color},{config.sung_outline_color},{config.shadow_color},0,0,0,0,100,100,{config.ruby_letter_spacing},0,1,{config.ruby_outline_width},{config.shadow_depth},7,0,0,0,1
Style: KirakaraRomajiSung,{config.font_name},{config.romaji_font_size},{config.sung_color},{config.sung_color},{config.sung_outline_color},{config.shadow_color},-1,0,0,0,100,100,{config.romaji_letter_spacing},0,1,{config.romaji_outline_width},{config.shadow_depth},7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""
