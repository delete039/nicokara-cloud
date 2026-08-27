from __future__ import annotations

import json

import pytest

from app.services.reviewed_artifacts import (
    ReviewedArtifactError,
    classify_reviewed_artifact,
)


def reviewed_lyrics_payload() -> dict:
    return {
        "provider": "deepseek",
        "source_text": "物語",
        "lines": [
            {
                "source": "物語",
                "surface": "物語",
                "reading": "ものがたり",
                "tokens": [
                    {
                        "surface": "物語",
                        "reading": "ものがたり",
                        "alignment_pronunciation": "モノガタリ",
                    }
                ],
            }
        ],
        "warnings": [],
    }


def reviewed_timeline_payload() -> dict:
    return {
        "confidence": 1.0,
        "alignment_engine": "fa_kara_mms",
        "alignment_model": "MMS_FA",
        "warnings": ["browser_reviewed"],
        "lines": [
            {
                "surface": "物語",
                "reading": "ものがたり",
                "start_ms": 1000,
                "end_ms": 1800,
                "confidence": 1.0,
                "tokens": [
                    {
                        "surface": "物語",
                        "reading": "ものがたり",
                        "start_ms": 1000,
                        "end_ms": 1800,
                        "confidence": 1.0,
                        "moras": [
                            {
                                "reading": "も",
                                "start_ms": 1000,
                                "end_ms": 1200,
                                "matched": True,
                                "confidence": 1.0,
                            },
                            {
                                "reading": "の",
                                "start_ms": 1200,
                                "end_ms": 1400,
                                "matched": True,
                                "confidence": 1.0,
                            },
                            {
                                "reading": "が",
                                "start_ms": 1400,
                                "end_ms": 1600,
                                "matched": True,
                                "confidence": 1.0,
                            },
                            {
                                "reading": "た",
                                "start_ms": 1600,
                                "end_ms": 1700,
                                "matched": True,
                                "confidence": 1.0,
                            },
                            {
                                "reading": "り",
                                "start_ms": 1700,
                                "end_ms": 1800,
                                "matched": True,
                                "confidence": 1.0,
                            },
                        ],
                    }
                ],
            }
        ],
    }


def test_classifies_current_reviewed_lyrics_export_by_structure() -> None:
    artifact = classify_reviewed_artifact(
        "renamed.json",
        json.dumps(reviewed_lyrics_payload(), ensure_ascii=False).encode(),
    )

    assert artifact.kind == "lyrics"
    assert artifact.lyrics is not None
    assert artifact.lyrics.lines[0].tokens[0].reading == "ものがたり"


def test_classifies_current_mora_timeline_export_by_structure() -> None:
    artifact = classify_reviewed_artifact(
        "anything.json",
        json.dumps(reviewed_timeline_payload(), ensure_ascii=False).encode(),
    )

    assert artifact.kind == "timeline"
    assert artifact.timeline is not None
    assert artifact.timeline.lines[0].tokens[0].moras[-1].end_ms == 1800


def test_classifies_utf8_bom_ass_export_and_preserves_content() -> None:
    content = (
        "[Script Info]\nScriptType: v4.00+\n"
        "[V4+ Styles]\nFormat: Name, Fontname\nStyle: Default,Arial\n"
        "[Events]\nFormat: Layer, Start, End, Style, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:02.00,Default,物語\n"
    )

    artifact = classify_reviewed_artifact(
        "renamed.ass", b"\xef\xbb\xbf" + content.encode("utf-8")
    )

    assert artifact.kind == "subtitle"
    assert artifact.subtitle == content


def test_rejects_timeline_with_zero_duration_mora() -> None:
    payload = reviewed_timeline_payload()
    payload["lines"][0]["tokens"][0]["moras"][0]["end_ms"] = 1000

    with pytest.raises(ReviewedArtifactError, match="mora"):
        classify_reviewed_artifact("timeline.json", json.dumps(payload).encode())


def test_rejects_unrecognized_json_instead_of_treating_it_as_lyrics() -> None:
    with pytest.raises(ReviewedArtifactError, match="本站导出的"):
        classify_reviewed_artifact("unknown.json", b'{"hello":"world"}')
