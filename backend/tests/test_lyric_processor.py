from __future__ import annotations

import importlib
import json
import re
from dataclasses import replace

import pytest

from app.lyrics.models import LyricDocument


class FakeJsonClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        self.calls.append((system_prompt, user_prompt))
        return self.response


def test_local_processor_generates_hiragana_and_tokens() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    if not hasattr(processor_module, "LocalJapaneseLyricProcessor"):
        pytest.fail("Local Japanese lyric processor is not implemented")

    processor = processor_module.LocalJapaneseLyricProcessor()
    document = processor.process("物語")

    assert document.provider == "local"
    assert document.lines[0].surface == "物語"
    assert document.lines[0].reading == "ものがたり"
    assert "".join(token.surface for token in document.lines[0].tokens) == (
        "物語"
    )
    assert [
        (token.surface, token.reading)
        for token in document.lines[0].tokens
    ] == [("物", "もの"), ("語", "がたり")]
    assert document.warnings == ["local_reading_may_be_inaccurate"]


def test_local_processor_prefers_janome_compound_reading() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    processor = processor_module.LocalJapaneseLyricProcessor()

    document = processor.process("泣き声")

    line = document.lines[0]
    assert line.reading == "なきごえ"
    assert [(token.surface, token.reading) for token in line.tokens] == [
        ("泣", "な"),
        ("き", "き"),
        ("声", "ごえ"),
    ]


def test_local_processor_prefers_janome_contextual_reading() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    processor = processor_module.LocalJapaneseLyricProcessor()

    document = processor.process("君は")

    line = document.lines[0]
    assert line.reading == "きみは"
    assert [
        (token.surface, token.reading, token.alignment_pronunciation)
        for token in line.tokens
    ] == [
        ("君", "きみ", None),
        ("は", "は", "wa"),
    ]


def test_local_processor_keeps_ambiguous_compound_reading_complete() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    processor = processor_module.LocalJapaneseLyricProcessor()

    document = processor.process("今日")

    tokens = document.lines[0].tokens
    assert [token.surface for token in tokens] == ["今", "日"]
    assert all(token.reading for token in tokens)
    assert "".join(token.reading for token in tokens) == "きょう"


def test_local_processor_uses_kana_suffix_as_reading_anchor() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    processor = processor_module.LocalJapaneseLyricProcessor()

    document = processor.process("大人しい")

    tokens = document.lines[0].tokens
    assert [(token.surface, token.reading) for token in tokens] == [
        ("大", "おと"),
        ("人", "な"),
        ("しい", "しい"),
    ]
    assert "".join(token.reading for token in tokens) == "おとなしい"


def test_local_processor_generates_editable_kana_for_latin_words_and_digits() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    processor = processor_module.LocalJapaneseLyricProcessor()

    document = processor.process("Darling Mother Get you Die for 2")

    line = document.lines[0]
    foreign_tokens = [
        token
        for token in line.tokens
        if re.search(r"[A-Za-z0-9]", token.surface)
    ]
    assert [(token.surface, token.reading) for token in foreign_tokens] == [
        ("Darling", "だーりんぐ"),
        ("Mother", "まざー"),
        ("Get", "げっと"),
        ("you", "ゆー"),
        ("Die", "だい"),
        ("for", "ふぉー"),
        ("2", "に"),
    ]
    assert re.search(r"[A-Za-z0-9]", line.reading) is None


@pytest.mark.parametrize(
    ("surface", "reading"),
    [
        ("80億分の1", "はちじゅうおくぶんのいち"),
        ("1000メーター", "せんめーたー"),
        ("100分", "ひゃっぷん"),
        ("3泊4日", "さんぱくよっか"),
        ("1人", "ひとり"),
        ("8月15日", "はちがつじゅうごにち"),
        ("午後12時半", "ごごじゅうにじはん"),
    ],
)
def test_local_processor_resolves_standard_numeric_phrases(
    surface: str,
    reading: str,
) -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    processor = processor_module.LocalJapaneseLyricProcessor()

    document = processor.process(surface)

    line = document.lines[0]
    assert line.surface == surface
    assert line.reading == reading
    assert "".join(token.surface for token in line.tokens) == surface


def test_local_processor_keeps_calendar_date_token_readings_nonempty() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    processor = processor_module.LocalJapaneseLyricProcessor()

    document = processor.process("1月1日")

    line = document.lines[0]
    assert line.reading == "いちがつついたち"
    assert all(token.reading for token in line.tokens)


@pytest.mark.parametrize("surface", ["12345ire", "50:50", "321", "1LDK"])
def test_local_processor_keeps_ambiguous_numeric_surface_editable(
    surface: str,
) -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    processor = processor_module.LocalJapaneseLyricProcessor()

    document = processor.process(surface)

    line = document.lines[0]
    assert line.surface == surface
    assert "".join(token.surface for token in line.tokens) == surface
    assert re.search(r"[A-Za-z0-9]", line.reading) is None


def test_local_processor_parses_fa_kara_explicit_annotations() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    processor = processor_module.LocalJapaneseLyricProcessor()

    document = processor.process("{知|し}るも[の|n]は{無|な}い")

    line = document.lines[0]
    assert line.surface == "知るものは無い"
    assert line.reading == "しるものはない"
    assert "{" not in line.surface
    assert "[" not in line.surface
    explicit = [
        (token.surface, token.reading, token.alignment_pronunciation)
        for token in line.tokens
        if token.alignment_pronunciation is not None
    ]
    assert explicit == [("の", "の", "n"), ("は", "は", "wa")]


def test_local_processor_splits_multi_kanji_explicit_reading() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    processor = processor_module.LocalJapaneseLyricProcessor()

    document = processor.process("{物語|ものがたり}")

    line = document.lines[0]
    assert [(token.surface, token.reading) for token in line.tokens] == [
        ("物", "もの"),
        ("語", "がたり"),
    ]
    assert line.surface == "物語"
    assert line.reading == "ものがたり"


def test_local_processor_rejects_malformed_fa_kara_annotations() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    processor = processor_module.LocalJapaneseLyricProcessor()

    with pytest.raises(
        processor_module.LyricProcessingError,
        match="FA-Kara",
    ):
        processor.process("{知|しる")


def test_deepseek_reviewer_applies_contextual_patch_to_local_tokens() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    local = processor_module.LocalJapaneseLyricProcessor().process(
        "無き声\n君は"
    )
    client = FakeJsonClient(
        {
            "corrections": [
                {
                    "line_index": 0,
                    "start_token": 0,
                    "end_token": 3,
                    "surface": "無き声",
                    "current_reading": "なきこえ",
                    "corrected_reading": "なきごえ",
                }
            ]
        }
    )
    reviewer = processor_module.DeepSeekReadingReviewer(client=client)

    reviewed = reviewer.review(local)

    assert reviewed.provider == "local+deepseek"
    assert reviewed.lines[0].surface == "無き声"
    assert reviewed.lines[0].reading == "なきごえ"
    assert reviewed.lines[1].reading == "きみは"
    assert reviewed.lines[1].tokens[-1].alignment_pronunciation == "wa"
    payload = json.loads(client.calls[0][1])
    prompt = client.calls[0][0]
    assert "不得修改歌词表面文字" in prompt
    assert "不要重新生成全文或 token" in prompt
    assert "不得修正含英文或数字的范围" in prompt
    assert "未提供的音频" in prompt
    assert payload["lines"][0] == {
        "line_index": 0,
        "surface": "無き声",
        "tokens": [
            {"token_index": 0, "surface": "無", "reading": "な"},
            {"token_index": 1, "surface": "き", "reading": "き"},
            {"token_index": 2, "surface": "声", "reading": "こえ"},
        ],
    }


def test_deepseek_reviewer_marks_success_when_no_patch_is_needed() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    local = processor_module.LocalJapaneseLyricProcessor().process("泣き声")
    reviewer = processor_module.DeepSeekReadingReviewer(
        client=FakeJsonClient({"corrections": []})
    )

    reviewed = reviewer.review(local)

    assert reviewed.provider == "local+deepseek"
    assert reviewed.lines == local.lines
    assert reviewed.warnings == local.warnings


def test_deepseek_reviewer_allows_only_surface_anchored_spaces() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    local = processor_module.LocalJapaneseLyricProcessor().process("泣き 声")
    reviewer = processor_module.DeepSeekReadingReviewer(
        client=FakeJsonClient(
            {
                "corrections": [
                    {
                        "line_index": 0,
                        "start_token": 0,
                        "end_token": 4,
                        "surface": "泣き 声",
                        "current_reading": "なき こえ",
                        "corrected_reading": "なき ごえ",
                    }
                ]
            }
        )
    )

    reviewed = reviewer.review(local)

    assert reviewed.lines[0].reading == "なき ごえ"
    assert [(token.surface, token.reading) for token in reviewed.lines[0].tokens] == [
        ("泣", "な"),
        ("き ", "き "),
        ("声", "ごえ"),
    ]


@pytest.mark.parametrize(
    ("text", "corrections", "message"),
    [
        (
            "無き声",
            [
                {
                    "line_index": 3,
                    "start_token": 0,
                    "end_token": 1,
                    "surface": "無",
                    "current_reading": "な",
                    "corrected_reading": "む",
                }
            ],
            "line",
        ),
        (
            "無き声",
            [
                {
                    "line_index": 0,
                    "start_token": 1,
                    "end_token": 1,
                    "surface": "",
                    "current_reading": "",
                    "corrected_reading": "な",
                }
            ],
            "range",
        ),
        (
            "無き声",
            [
                {
                    "line_index": 0,
                    "start_token": 0,
                    "end_token": 2,
                    "surface": "無き",
                    "current_reading": "なき",
                    "corrected_reading": "むき",
                },
                {
                    "line_index": 0,
                    "start_token": 1,
                    "end_token": 3,
                    "surface": "き声",
                    "current_reading": "きこえ",
                    "corrected_reading": "きごえ",
                },
            ],
            "overlap",
        ),
        (
            "無き声",
            [
                {
                    "line_index": 0,
                    "start_token": 0,
                    "end_token": 3,
                    "surface": "泣き声",
                    "current_reading": "なきこえ",
                    "corrected_reading": "なきごえ",
                }
            ],
            "surface",
        ),
        (
            "無き声",
            [
                {
                    "line_index": 0,
                    "start_token": 0,
                    "end_token": 3,
                    "surface": "無き声",
                    "current_reading": "むきこえ",
                    "corrected_reading": "なきごえ",
                }
            ],
            "current reading",
        ),
        (
            "1人",
            [
                {
                    "line_index": 0,
                    "start_token": 0,
                    "end_token": 1,
                    "surface": "1",
                    "current_reading": "ひと",
                    "corrected_reading": "わん",
                }
            ],
            "Latin or digits",
        ),
        (
            "君は",
            [
                {
                    "line_index": 0,
                    "start_token": 1,
                    "end_token": 2,
                    "surface": "は",
                    "current_reading": "は",
                    "corrected_reading": "わ",
                }
            ],
            "alignment pronunciation",
        ),
        (
            "無き声",
            [
                {
                    "line_index": 0,
                    "start_token": 0,
                    "end_token": 3,
                    "surface": "無き声",
                    "current_reading": "なきこえ",
                    "corrected_reading": "naki1",
                }
            ],
            "hiragana",
        ),
        (
            "無き声",
            [
                {
                    "line_index": 0,
                    "start_token": 0,
                    "end_token": 3,
                    "surface": "無き声",
                    "current_reading": "なきこえ",
                    "corrected_reading": "なごえ",
                }
            ],
            "literal kana",
        ),
        (
            "無き声",
            [
                {
                    "line_index": 0,
                    "start_token": 0,
                    "end_token": 3,
                    "surface": "無き声",
                    "current_reading": "なきこえ",
                    "corrected_reading": "なきこえ",
                }
            ],
            "no-op",
        ),
        (
            "物語",
            [
                {
                    "line_index": 0,
                    "start_token": 0,
                    "end_token": 2,
                    "surface": "物語",
                    "current_reading": "ものがたり",
                    "corrected_reading": "あ",
                }
            ],
            "empty token reading",
        ),
        (
            "声",
            [
                {
                    "line_index": 0,
                    "start_token": 0,
                    "end_token": 1,
                    "surface": "声",
                    "current_reading": "こえ",
                    "corrected_reading": "こえ ",
                }
            ],
            "kanji reading",
        ),
        (
            "声",
            [
                {
                    "line_index": 0,
                    "start_token": 0,
                    "end_token": 1,
                    "surface": "声",
                    "current_reading": "こえ",
                    "corrected_reading": "こ え",
                }
            ],
            "kanji reading",
        ),
        (
            "物語",
            [
                {
                    "line_index": 0,
                    "start_token": 0,
                    "end_token": 2,
                    "surface": "物語",
                    "current_reading": "ものがたり",
                    "corrected_reading": "あ ",
                }
            ],
            "kanji reading",
        ),
        (
            "無き声",
            [
                {
                    "line_index": 0.5,
                    "start_token": 0,
                    "end_token": 3,
                    "surface": "無き声",
                    "current_reading": "なきこえ",
                    "corrected_reading": "なきごえ",
                }
            ],
            "integer",
        ),
        (
            "無き声",
            [
                {
                    "line_index": 0,
                    "start_token": "0",
                    "end_token": 3,
                    "surface": "無き声",
                    "current_reading": "なきこえ",
                    "corrected_reading": "なきごえ",
                }
            ],
            "integer",
        ),
        (
            "無き声",
            [
                {
                    "line_index": 0,
                    "start_token": False,
                    "end_token": 3,
                    "surface": "無き声",
                    "current_reading": "なきこえ",
                    "corrected_reading": "なきごえ",
                }
            ],
            "integer",
        ),
    ],
)
def test_deepseek_reviewer_rejects_unsafe_corrections_atomically(
    text: str,
    corrections: list[dict],
    message: str,
) -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    local = processor_module.LocalJapaneseLyricProcessor().process(text)
    reviewer = processor_module.DeepSeekReadingReviewer(
        client=FakeJsonClient({"corrections": corrections})
    )

    with pytest.raises(processor_module.LyricProcessingError, match=message):
        reviewer.review(local)


def test_reviewed_processor_keeps_single_local_result_when_review_fails() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")

    class RecordingBase:
        def __init__(self) -> None:
            self.texts: list[str] = []

        def process(self, text: str) -> LyricDocument:
            self.texts.append(text)
            return LyricDocument(
                provider="local",
                source_text=text,
                warnings=["local_reading_may_be_inaccurate"],
            )

    class FailingReviewer:
        def __init__(self) -> None:
            self.documents: list[LyricDocument] = []

        def review(self, document: LyricDocument) -> LyricDocument:
            self.documents.append(document)
            raise RuntimeError("DeepSeek unavailable")

    base = RecordingBase()
    reviewer = FailingReviewer()
    processor = processor_module.ReviewedLyricProcessor(
        base=base,
        reviewer=reviewer,
    )

    document = processor.process("物語")

    assert base.texts == ["物語"]
    assert reviewer.documents[0].source_text == "物語"
    assert document.provider == "local"
    assert document.warnings == [
        "local_reading_may_be_inaccurate",
        "deepseek_review_failed:RuntimeError",
    ]


def test_reviewed_processor_records_review_lifecycle_without_lyrics() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")

    class RecordingEvents:
        def __init__(self) -> None:
            self.items: list[dict] = []

        def emit(self, **event) -> bool:
            self.items.append(event)
            return True

    class Reviewer:
        class Client:
            model = "deepseek-test"
            timeout_seconds = 12

        client = Client()

        def review(self, document: LyricDocument) -> LyricDocument:
            return replace(document, provider="local+deepseek")

    events = RecordingEvents()
    processor = processor_module.ReviewedLyricProcessor(
        base=processor_module.LocalJapaneseLyricProcessor(),
        reviewer=Reviewer(),
        event_logger=events,
    )

    processor.process("秘密の歌詞")

    assert [item["event"] for item in events.items] == [
        "external.started",
        "external.completed",
    ]
    assert events.items[0]["details"] == {
        "attempt": 1,
        "character_count": 5,
        "line_count": 1,
        "model": "deepseek-test",
        "timeout_seconds": 12,
    }
    assert events.items[1]["duration_ms"] >= 0
    assert "秘密の歌詞" not in str(events.items)


def test_reviewed_processor_records_review_failure_and_keeps_local_result() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")

    class RecordingEvents:
        def __init__(self) -> None:
            self.items: list[dict] = []

        def emit(self, **event) -> bool:
            self.items.append(event)
            return True

    class FailingReviewer:
        def review(self, document: LyricDocument) -> LyricDocument:
            raise RuntimeError("temporary upstream failure")

    events = RecordingEvents()
    processor = processor_module.ReviewedLyricProcessor(
        base=processor_module.LocalJapaneseLyricProcessor(),
        reviewer=FailingReviewer(),
        event_logger=events,
    )

    processor.process("東京")

    assert [item["event"] for item in events.items] == [
        "external.started",
        "external.failed",
        "stage.fallback",
    ]
    assert events.items[1]["details"]["retry_count"] == 0
    assert events.items[2]["details"]["reason"] == "deepseek_review_failed"


def test_reviewed_processor_does_not_send_fa_kara_to_deepseek() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")

    class RecordingReviewer:
        def __init__(self) -> None:
            self.calls = 0

        def review(self, document: LyricDocument) -> LyricDocument:
            self.calls += 1
            return replace(document, provider="local+deepseek")

    reviewer = RecordingReviewer()
    processor = processor_module.ReviewedLyricProcessor(
        base=processor_module.LocalJapaneseLyricProcessor(),
        reviewer=reviewer,
    )

    document = processor.process("{今日|きょう}")

    assert reviewer.calls == 0
    assert document.provider == "local"
