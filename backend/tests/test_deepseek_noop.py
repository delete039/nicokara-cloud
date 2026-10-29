from dataclasses import asdict

import pytest

from app.lyrics.processor import (
    DeepSeekReadingReviewer,
    LocalJapaneseLyricProcessor,
    LyricProcessingError,
)


def review(document, corrections):
    class Client:
        def complete_json(self, **kwargs):
            return {"corrections": corrections}

    return DeepSeekReadingReviewer(client=Client()).review(document)


def correction(line, start, end, surface, current, corrected):
    return dict(line_index=line, start_token=start, end_token=end,
                surface=surface, current_reading=current,
                corrected_reading=corrected)


def test_unchanged_readings_preserve_tokens_and_alignment_pronunciation():
    local = LocalJapaneseLyricProcessor().process("君は")
    before = asdict(local)
    reviewed = review(local, [correction(0, 0, 2, "君は", "きみは", "きみは")])
    assert reviewed.provider == "local+deepseek"
    assert reviewed.lines == local.lines
    assert reviewed.lines[0].tokens[-1].alignment_pronunciation == "wa"
    assert reviewed.warnings == local.warnings
    assert asdict(local) == before


def test_unchanged_entries_do_not_discard_valid_corrections():
    local = LocalJapaneseLyricProcessor().process("無き声\n君は")
    reviewed = review(local, [
        correction(0, 0, 3, "無き声", "なきこえ", "なきこえ"),
        correction(0, 0, 3, "無き声", "なきこえ", "なきごえ"),
        correction(1, 0, 2, "君は", "きみは", "きみは"),
    ])
    assert reviewed.provider == "local+deepseek"
    assert reviewed.lines[0].reading == "なきごえ"
    assert reviewed.lines[1] == local.lines[1]
    assert local.lines[0].reading == "なきこえ"


@pytest.mark.parametrize("field,value", [
    ("surface", "別"), ("start_token", -1), ("line_index", 9),
    ("start_token", False), ("current_reading", "べつ"),
])
def test_unchanged_entries_still_require_valid_source_anchors(field, value):
    local = LocalJapaneseLyricProcessor().process("君は")
    item = correction(0, 0, 2, "君は", "きみは", "きみは")
    item[field] = value
    if field == "current_reading":
        item["corrected_reading"] = value
    with pytest.raises(LyricProcessingError):
        review(local, [item])
