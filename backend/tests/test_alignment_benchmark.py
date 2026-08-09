from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.alignment.models import (
    AlignedLine,
    AlignedMora,
    AlignedToken,
    LyricTimeline,
)


def timeline(*spans: tuple[str, int, int]) -> LyricTimeline:
    moras = [
        AlignedMora(
            reading=reading,
            start_ms=start,
            end_ms=end,
            matched=True,
            confidence=1.0,
        )
        for reading, start, end in spans
    ]
    token = AlignedToken(
        surface="歌词",
        reading="".join(mora.reading for mora in moras),
        start_ms=moras[0].start_ms,
        end_ms=moras[-1].end_ms,
        confidence=1.0,
        moras=moras,
    )
    return LyricTimeline(
        confidence=1.0,
        lines=[
            AlignedLine(
                surface="歌词",
                reading=token.reading,
                start_ms=token.start_ms,
                end_ms=token.end_ms,
                confidence=1.0,
                tokens=[token],
            )
        ],
    )


def test_compare_timelines_reports_repeatable_mora_error_metrics() -> None:
    from app.alignment.benchmark import compare_timelines

    reference = timeline(("き", 100, 200), ("み", 200, 300))
    candidate = timeline(("き", 120, 190), ("み", 230, 320))

    result = compare_timelines(reference, candidate)

    assert result.mora_count == 2
    assert result.mean_absolute_error_ms == pytest.approx(20)
    assert result.median_absolute_error_ms == pytest.approx(20)
    assert result.max_absolute_error_ms == 30


def test_compare_timelines_rejects_a_different_mora_sequence() -> None:
    from app.alignment.benchmark import BenchmarkDataError, compare_timelines

    with pytest.raises(BenchmarkDataError, match="mora sequence"):
        compare_timelines(
            timeline(("き", 100, 200)),
            timeline(("み", 100, 200)),
        )


def test_summarize_benchmark_cases_includes_failure_rate_and_resources() -> None:
    from app.alignment.benchmark import BenchmarkCaseResult, summarize_cases

    summary = summarize_cases(
        [
            BenchmarkCaseResult(
                name="song-a",
                mora_count=10,
                mean_absolute_error_ms=30,
                median_absolute_error_ms=25,
                max_absolute_error_ms=90,
                elapsed_seconds=8.5,
                peak_rss_mb=900,
            ),
            BenchmarkCaseResult(
                name="song-b",
                error="alignment failed",
            ),
        ]
    )

    assert summary["case_count"] == 2
    assert summary["success_count"] == 1
    assert summary["failure_rate"] == 0.5
    assert summary["mean_absolute_error_ms"] == 30
    assert summary["mean_elapsed_seconds"] == 8.5
    assert summary["peak_rss_mb"] == 900


def test_benchmark_cli_groups_fixed_dataset_results_by_engine(
    tmp_path: Path,
) -> None:
    from app.alignment.benchmark_cli import main

    reference_path = tmp_path / "reference.json"
    candidate_path = tmp_path / "candidate.json"
    reference_path.write_text(
        json.dumps(timeline(("き", 100, 200)).to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    candidate_path.write_text(
        json.dumps(timeline(("き", 120, 220)).to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "name": "song-a",
                        "reference": "reference.json",
                        "engines": {
                            "fa_kara_mms": {
                                "timeline": "candidate.json",
                                "elapsed_seconds": 7.2,
                                "peak_rss_mb": 820,
                            }
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "report.json"

    main([str(manifest_path), "--output", str(output_path)])

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["engines"]["fa_kara_mms"]["summary"] == {
        "case_count": 1,
        "success_count": 1,
        "failure_rate": 0.0,
        "mean_absolute_error_ms": 20,
        "median_absolute_error_ms": 20.0,
        "mean_elapsed_seconds": 7.2,
        "peak_rss_mb": 820.0,
    }
