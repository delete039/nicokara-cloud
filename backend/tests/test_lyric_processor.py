from __future__ import annotations

import importlib
import re

import pytest

from app.lyrics.models import LyricDocument


class FakeJsonClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        self.calls.append((system_prompt, user_prompt))
        return self.response


def test_deepseek_processor_returns_ruby_ready_lyrics() -> None:
    try:
        processor_module = importlib.import_module("app.lyrics.processor")
    except ModuleNotFoundError:
        pytest.fail("DeepSeek lyric processor is not implemented")

    client = FakeJsonClient(
        {
            "lines": [
                {
                    "surface": "君の知らない物語",
                    "reading": "きみのしらないものがたり",
                    "tokens": [
                        {"surface": "君", "reading": "きみ"},
                        {"surface": "の", "reading": "の"},
                        {"surface": "知らない", "reading": "しらない"},
                        {"surface": "物語", "reading": "ものがたり"},
                    ],
                }
            ]
        }
    )
    processor = processor_module.DeepSeekLyricProcessor(client=client)

    document = processor.process("  君の知らない物語  \n\n")

    assert document.provider == "deepseek"
    assert document.source_text == "君の知らない物語"
    assert len(document.lines) == 1
    line = document.lines[0]
    assert line.source == "君の知らない物語"
    assert line.surface == "君の知らない物語"
    assert line.reading == "きみのしらないものがたり"
    assert "".join(token.surface for token in line.tokens) == line.surface
    assert [(token.surface, token.reading) for token in line.tokens] == [
        ("君", "きみ"),
        ("の", "の"),
        ("知", "し"),
        ("ら", "ら"),
        ("な", "な"),
        ("い", "い"),
        ("物", "もの"),
        ("語", "がたり"),
    ]
    assert client.calls
    assert "JSON" in client.calls[0][0]
    assert "每个汉字" in client.calls[0][0]


def test_deepseek_processor_requests_kana_readings_for_latin_and_digits() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    client = FakeJsonClient(
        {
            "lines": [
                {
                    "surface": "LOVE 39",
                    "reading": "らぶ さんきゅー",
                    "tokens": [
                        {"surface": "LOVE", "reading": "らぶ"},
                        {"surface": " ", "reading": " "},
                        {"surface": "39", "reading": "さんきゅー"},
                    ],
                }
            ]
        }
    )

    document = processor_module.DeepSeekLyricProcessor(client=client).process(
        "LOVE 39"
    )

    prompt = client.calls[0][0]
    assert "英文或数字" in prompt
    assert "实际唱法" in prompt
    assert "平假名" in prompt
    assert document.lines[0].reading == "らぶ さんきゅー"


def test_deepseek_processor_retries_unconverted_latin_reading_once() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")

    class SequenceJsonClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []
            self.responses = [
                {
                    "lines": [
                        {
                            "surface": "LOVE",
                            "reading": "LOVE",
                            "tokens": [
                                {"surface": "LOVE", "reading": "LOVE"}
                            ],
                        }
                    ]
                },
                {
                    "lines": [
                        {
                            "surface": "LOVE",
                            "reading": "らぶ",
                            "tokens": [
                                {"surface": "LOVE", "reading": "らぶ"}
                            ],
                        }
                    ]
                },
            ]

        def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict:
            self.calls.append((system_prompt, user_prompt))
            return self.responses[len(self.calls) - 1]

    client = SequenceJsonClient()
    document = processor_module.DeepSeekLyricProcessor(client=client).process(
        "LOVE"
    )

    assert len(client.calls) == 2
    assert "纠正" in client.calls[1][1]
    assert document.lines[0].reading == "らぶ"
    assert document.lines[0].tokens[0].reading == "らぶ"


def test_deepseek_processor_rejects_unconverted_reading_after_retry() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")

    class InvalidJsonClient:
        def __init__(self) -> None:
            self.call_count = 0

        def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict:
            self.call_count += 1
            return {
                "lines": [
                    {
                        "surface": "LOVE",
                        "reading": "LOVE",
                        "tokens": [
                            {"surface": "LOVE", "reading": "LOVE"}
                        ],
                    }
                ]
            }

    client = InvalidJsonClient()
    with pytest.raises(
        processor_module.LyricProcessingError,
        match="kana reading",
    ):
        processor_module.DeepSeekLyricProcessor(client=client).process("LOVE")

    assert client.call_count == 2


def test_deepseek_processor_rejects_tokens_that_change_surface() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    client = FakeJsonClient(
        {
            "lines": [
                {
                    "surface": "君の知らない物語",
                    "reading": "きみのしらないものがたり",
                    "tokens": [
                        {"surface": "君の物語", "reading": "きみのものがたり"}
                    ],
                }
            ]
        }
    )
    processor = processor_module.DeepSeekLyricProcessor(client=client)

    with pytest.raises(
        processor_module.LyricProcessingError,
        match="tokens do not reconstruct surface",
    ):
        processor.process("君の知らない物語")


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
        ("し", "し"),
        ("い", "い"),
    ]
    assert "".join(token.reading for token in tokens) == "おとなしい"


def test_local_processor_uses_fa_kara_alignment_markers() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    processor = processor_module.LocalJapaneseLyricProcessor()

    document = processor.process("げっと LOVE 物語 だー")

    assert [(token.surface, token.reading) for token in document.lines[0].tokens] == [
        ("げっ", "げっ"),
        ("と", "と"),
        (" ", " "),
        ("LOVE", "らぶ"),
        (" ", " "),
        ("物", "もの"),
        ("語", "がたり"),
        (" ", " "),
        ("だー", "だー"),
    ]


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


def test_resilient_processor_falls_back_when_deepseek_fails() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")
    if not hasattr(processor_module, "ResilientLyricProcessor"):
        pytest.fail("Resilient lyric processor is not implemented")

    class FailingPrimary:
        def process(self, text: str) -> LyricDocument:
            raise RuntimeError("DeepSeek unavailable")

    class RecordingFallback:
        def __init__(self) -> None:
            self.texts: list[str] = []

        def process(self, text: str) -> LyricDocument:
            self.texts.append(text)
            return LyricDocument(
                provider="local",
                source_text=text,
                warnings=["local_reading_may_be_inaccurate"],
            )

    fallback = RecordingFallback()
    processor = processor_module.ResilientLyricProcessor(
        primary=FailingPrimary(),
        fallback=fallback,
    )

    document = processor.process("物語")

    assert fallback.texts == ["物語"]
    assert document.provider == "local"
    assert document.warnings == [
        "local_reading_may_be_inaccurate",
        "deepseek_fallback:RuntimeError",
    ]


def test_resilient_processor_records_deepseek_call_lifecycle_without_lyrics() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")

    class RecordingEvents:
        def __init__(self) -> None:
            self.items: list[dict] = []

        def emit(self, **event) -> bool:
            self.items.append(event)
            return True

    class Primary:
        class Client:
            model = "deepseek-test"
            timeout_seconds = 12

        client = Client()

        def process(self, text: str) -> LyricDocument:
            return LyricDocument(provider="deepseek", source_text=text, lines=[])

    events = RecordingEvents()
    processor = processor_module.ResilientLyricProcessor(
        primary=Primary(),
        fallback=object(),
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


def test_resilient_processor_records_deepseek_failure_and_fallback() -> None:
    processor_module = importlib.import_module("app.lyrics.processor")

    class RecordingEvents:
        def __init__(self) -> None:
            self.items: list[dict] = []

        def emit(self, **event) -> bool:
            self.items.append(event)
            return True

    class FailingPrimary:
        def process(self, text: str) -> LyricDocument:
            raise RuntimeError("temporary upstream failure")

    class Fallback:
        def process(self, text: str) -> LyricDocument:
            return LyricDocument(provider="local", source_text=text, lines=[])

    events = RecordingEvents()
    processor = processor_module.ResilientLyricProcessor(
        primary=FailingPrimary(),
        fallback=Fallback(),
        event_logger=events,
    )

    processor.process("東京")

    assert [item["event"] for item in events.items] == [
        "external.started",
        "external.failed",
        "stage.fallback",
    ]
    assert events.items[1]["details"]["retry_count"] == 0
    assert events.items[2]["details"]["reason"] == "deepseek_unavailable"
