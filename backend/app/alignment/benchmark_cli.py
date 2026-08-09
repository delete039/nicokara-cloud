from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.alignment.benchmark import (
    BenchmarkCaseResult,
    compare_timelines,
    summarize_cases,
)
from app.alignment.review import lyric_timeline_from_dict


def _load_timeline(path: Path):
    return lyric_timeline_from_dict(
        json.loads(path.read_text(encoding="utf-8"))
    )


def build_report(manifest_path: Path) -> dict[str, Any]:
    base_dir = manifest_path.resolve().parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_engine: dict[str, list[BenchmarkCaseResult]] = defaultdict(list)

    for case in manifest.get("cases", []):
        name = str(case["name"])
        try:
            reference = _load_timeline(base_dir / case["reference"])
        except Exception as exc:
            for engine_name in case.get("engines", {}):
                by_engine[engine_name].append(
                    BenchmarkCaseResult(
                        name=name,
                        error=f"reference:{type(exc).__name__}",
                    )
                )
            continue

        for engine_name, engine_result in case.get("engines", {}).items():
            try:
                candidate = _load_timeline(
                    base_dir / engine_result["timeline"]
                )
                metrics = compare_timelines(reference, candidate)
                result = BenchmarkCaseResult(
                    name=name,
                    mora_count=metrics.mora_count,
                    mean_absolute_error_ms=(
                        metrics.mean_absolute_error_ms
                    ),
                    median_absolute_error_ms=(
                        metrics.median_absolute_error_ms
                    ),
                    max_absolute_error_ms=metrics.max_absolute_error_ms,
                    elapsed_seconds=_optional_float(
                        engine_result.get("elapsed_seconds")
                    ),
                    peak_rss_mb=_optional_float(
                        engine_result.get("peak_rss_mb")
                    ),
                )
            except Exception as exc:
                result = BenchmarkCaseResult(
                    name=name,
                    error=f"{type(exc).__name__}:{exc}",
                )
            by_engine[str(engine_name)].append(result)

    return {
        "manifest": str(manifest_path.resolve()),
        "engines": {
            engine: {
                "summary": summarize_cases(results),
                "cases": [result.to_dict() for result in results],
            }
            for engine, results in sorted(by_engine.items())
        },
    }


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Compare alignment timelines against fixed references."
    )
    parser.add_argument("manifest")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            build_report(Path(args.manifest)),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
