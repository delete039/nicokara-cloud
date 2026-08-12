from __future__ import annotations

import importlib

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
        ("らない", "らない"),
        ("物", "もの"),
        ("語", "がたり"),
    ]
    assert client.calls
    assert "JSON" in client.calls[0][0]
    assert "每个汉字" in client.calls[0][0]


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
        ("しい", "しい"),
    ]
    assert "".join(token.reading for token in tokens) == "おとなしい"


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
