from __future__ import annotations

from dataclasses import dataclass

from app.alignment.models import AlignedLine, LyricTimeline
from app.subtitle.karaoke_effect import (
    escape_ass_text,
    line_chunks,
    render_karaoke,
)
from app.subtitle.ruby import ruby_placements


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
    section_lead_ms: int = 3000
    long_interlude_ms: int = 12000
    fade_in_ms: int = 180
    fade_out_ms: int = 220
    sung_color: str = "&H000000A5"
    unsung_color: str = "&H00FFFFFF"
    outline_width: int = 5
    ruby_outline_width: int = 3

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
        if font_name not in {"Noto Sans JP", "Yu Gothic", "Microsoft YaHei"}:
            font_name = cls.font_name
        scale = 1.5
        font_size = number("font_size", 64, 48, 80)
        ruby_size = number("ruby_size", 26, 18, 38)
        stroke_width = number("stroke_width", 5, 2, 8)
        return cls(
            font_name=font_name,
            base_font_size=round(font_size * scale),
            ruby_font_size=round(ruby_size * scale),
            upper_y=round(number("upper_y", 430, 320, 560) * scale),
            lower_y=round(number("lower_y", 563, 440, 680) * scale),
            sung_color=ass_color("color_after", cls.sung_color),
            unsung_color=ass_color("color_before", cls.unsung_color),
            outline_width=round(stroke_width * scale),
            ruby_outline_width=max(1, round(stroke_width * 0.8 * scale)),
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
        for index, line in enumerate(timeline.lines):
            display_start = ass_time(self._display_start(timeline.lines, index))
            display_end = ass_time(self._display_end(timeline.lines, index))
            singing_start = ass_time(line.start_ms)
            tags = self._line_tags(index)
            events.append(
                self._dialogue(
                    1,
                    display_start,
                    display_end,
                    "KirakaraBase",
                    tags,
                    escape_ass_text(line.surface),
                )
            )
            events.extend(
                self._ruby_events(
                    line,
                    index,
                    display_start,
                    display_end,
                )
            )
            events.append(
                self._dialogue(
                    3,
                    singing_start,
                    display_end,
                    "KirakaraProgress",
                    tags,
                    render_karaoke(line_chunks(line)),
                )
            )
        return self._header() + "\n" + "\n".join(events) + "\n"

    def _display_start(
        self,
        lines: list[AlignedLine],
        index: int,
    ) -> int:
        line = lines[index]
        previous = lines[index - 1] if index > 0 else None
        if (
            previous is None
            or line.start_ms - previous.end_ms
            >= self.config.long_interlude_ms
        ):
            return max(0, line.start_ms - self.config.section_lead_ms)
        return previous.start_ms

    def _display_end(
        self,
        lines: list[AlignedLine],
        index: int,
    ) -> int:
        if index + 2 < len(lines):
            return self._display_start(lines, index + 2)
        return lines[index].end_ms

    def _line_tags(self, index: int) -> str:
        config = self.config
        if index % 2 == 0:
            alignment = 4
            x = config.upper_left_x
            y = config.upper_y
        else:
            alignment = 6
            x = config.lower_right_x
            y = config.lower_y
        return (
            rf"\an{alignment}\pos({x},{y})"
            rf"\fad({config.fade_in_ms},{config.fade_out_ms})"
        )

    def _line_center_x(self, line: AlignedLine, index: int) -> int:
        estimated_width = len(line.surface) * self.config.base_font_size * 0.68
        if index % 2 == 0:
            return round(self.config.upper_left_x + estimated_width / 2)
        return round(self.config.lower_right_x - estimated_width / 2)

    def _ruby_events(
        self,
        line: AlignedLine,
        index: int,
        start: str,
        end: str,
    ) -> list[str]:
        baseline_y = (
            self.config.upper_y if index % 2 == 0 else self.config.lower_y
        )
        return [
            self._dialogue(
                2,
                start,
                end,
                "KirakaraRuby",
                (
                    rf"\an2\pos({ruby.x},{ruby.y})"
                    rf"\fad({self.config.fade_in_ms},"
                    rf"{self.config.fade_out_ms})"
                ),
                escape_ass_text(ruby.text),
            )
            for ruby in ruby_placements(
                line,
                play_res_x=self.config.play_res_x,
                baseline_y=baseline_y,
                base_font_size=self.config.base_font_size,
                ruby_font_size=self.config.ruby_font_size,
                center_x=self._line_center_x(line, index),
            )
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
Style: KirakaraBase,{config.font_name},{config.base_font_size},{config.unsung_color},{config.unsung_color},&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{config.outline_width},0,4,0,0,0,1
Style: KirakaraRuby,{config.font_name},{config.ruby_font_size},{config.unsung_color},{config.unsung_color},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{config.ruby_outline_width},0,2,0,0,0,1
Style: KirakaraProgress,{config.font_name},{config.base_font_size},{config.sung_color},{config.unsung_color},&H00FFFFFF,&H00000000,-1,0,0,0,100,100,0,0,1,{config.outline_width},0,4,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""
