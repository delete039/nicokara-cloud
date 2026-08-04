from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from app.ai.whisper import (
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
)
from app.alignment.models import LyricTimeline
from app.core.database import Database
from app.lyrics.models import LyricDocument, LyricLine, LyricToken


class FakeExtractor:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path]] = []

    def extract(self, input_path: Path, output_path: Path) -> None:
        self.calls.append((input_path, output_path))
        output_path.write_bytes(b"wav")


class FakeTranscriber:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def transcribe(self, audio_path: Path) -> TranscriptDocument:
        self.calls.append(audio_path)
        return TranscriptDocument(
            language="ja",
            language_probability=0.98,
            duration_seconds=12.0,
            text="君の知らない物語",
            segments=[
                TranscriptSegment(
                    id=0,
                    text="君の知らない物語",
                    start_ms=1000,
                    end_ms=4000,
                    confidence=-0.1,
                    no_speech_probability=0.01,
                    words=[
                        TranscriptWord(
                            text="君の知らない物語",
                            start_ms=1000,
                            end_ms=4000,
                            confidence=0.93,
                        )
                    ],
                )
            ],
        )


def create_uploaded_job(database: Database, job_dir: Path) -> str:
    job_id = "f13ecf06-9ac4-486f-a5cd-b4959f02bc76"
    job_dir.mkdir(parents=True)
    video_path = job_dir / "input.mp4"
    video_path.write_bytes(b"video")
    database.create_job(
        job_id=job_id,
        original_video_name="song.mp4",
        video_size_bytes=5,
        video_sha256="abc",
        video_path=video_path,
        lyrics_source="text",
        lyrics_path=None,
    )
    return job_id


def test_pipeline_extracts_transcribes_and_persists_json(tmp_path: Path) -> None:
    try:
        pipeline_module = importlib.import_module("app.tasks.pipeline")
    except ModuleNotFoundError:
        pytest.fail("Transcription pipeline is not implemented")

    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_id = create_uploaded_job(database, job_dir)
    extractor = FakeExtractor()
    transcriber = FakeTranscriber()
    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=extractor,
        transcriber=transcriber,
    )

    pipeline.process(job_id)

    audio_path = job_dir / "audio.wav"
    transcript_path = job_dir / "transcript.json"
    assert extractor.calls == [(job_dir / "input.mp4", audio_path)]
    assert transcriber.calls == [audio_path]
    assert json.loads(transcript_path.read_text(encoding="utf-8"))["text"] == (
        "君の知らない物語"
    )
    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "TRANSCRIBED"
    assert job["stage"] == "TRANSCRIPTION_COMPLETE"
    assert job["progress"] == 100
    assert job["audio_path"] == str(audio_path)
    assert job["transcript_path"] == str(transcript_path)


def test_pipeline_stops_after_a_running_job_is_canceled(
    tmp_path: Path,
) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_id = create_uploaded_job(database, job_dir)

    class CancelingExtractor(FakeExtractor):
        def extract(self, input_path: Path, output_path: Path) -> None:
            super().extract(input_path, output_path)
            assert database.cancel_job(job_id)

    class UnexpectedTranscriber(FakeTranscriber):
        def transcribe(self, audio_path: Path) -> TranscriptDocument:
            pytest.fail("a canceled task must not start transcription")

    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=CancelingExtractor(),
        transcriber=UnexpectedTranscriber(),
    )

    pipeline.process(job_id)

    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "CANCELED"
    assert job["stage"] == "CANCELED_BY_USER"


def test_pipeline_marks_transcription_failure_in_database(tmp_path: Path) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_id = create_uploaded_job(database, job_dir)
    extractor = FakeExtractor()

    class FailingTranscriber:
        def transcribe(self, audio_path: Path) -> TranscriptDocument:
            raise RuntimeError("model could not load")

    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=extractor,
        transcriber=FailingTranscriber(),
    )

    with pytest.raises(RuntimeError, match="model could not load"):
        pipeline.process(job_id)

    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "FAILED"
    assert job["stage"] == "TRANSCRIBING"
    assert job["error_code"] == "TRANSCRIPTION_FAILED"
    assert job["error_message"] == (
        "Processing failed during audio transcription. "
        "Check server logs with this job ID."
    )


def test_pipeline_marks_vocal_removal_failure_in_database(
    tmp_path: Path,
) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_id = create_uploaded_job(database, job_dir)
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET vocal_mode = 'off' WHERE id = ?",
            (job_id,),
        )

    class StereoExtractor(FakeExtractor):
        def extract_stereo(
            self,
            input_path: Path,
            output_path: Path,
        ) -> None:
            output_path.write_bytes(b"stereo")

    class FailingVocalRemover:
        def remove_vocals(
            self,
            input_path: Path,
            output_path: Path,
        ) -> None:
            raise RuntimeError("packed stereo could not be decoded")

    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=StereoExtractor(),
        transcriber=FakeTranscriber(),
        vocal_remover=FailingVocalRemover(),
    )

    with pytest.raises(
        RuntimeError,
        match="packed stereo could not be decoded",
    ):
        pipeline.process(job_id)

    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "FAILED"
    assert job["stage"] == "REMOVING_VOCALS"
    assert job["progress"] == 25
    assert job["error_code"] == "VOCAL_REMOVAL_FAILED"


def test_pipeline_processes_uploaded_lyrics_after_transcription(tmp_path: Path) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_id = create_uploaded_job(database, job_dir)
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("物語\n", encoding="utf-8")
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET lyrics_path = ? WHERE id = ?",
            (str(lyrics_path), job_id),
        )

    class FakeLyricProcessor:
        def __init__(self) -> None:
            self.texts: list[str] = []

        def process(self, text: str) -> LyricDocument:
            self.texts.append(text)
            return LyricDocument(
                provider="local",
                source_text="物語",
                lines=[
                    LyricLine(
                        source="物語",
                        surface="物語",
                        reading="ものがたり",
                        tokens=[LyricToken(surface="物語", reading="ものがたり")],
                    )
                ],
            )

    lyric_processor = FakeLyricProcessor()
    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=FakeExtractor(),
        transcriber=FakeTranscriber(),
        lyric_processor=lyric_processor,
    )

    pipeline.process(job_id)

    processed_path = job_dir / "lyrics_processed.json"
    assert lyric_processor.texts == ["物語\n"]
    assert json.loads(processed_path.read_text(encoding="utf-8"))["provider"] == "local"
    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "LYRICS_PROCESSED"
    assert job["stage"] == "LYRIC_PROCESSING_COMPLETE"
    assert job["progress"] == 100
    assert job["lyrics_processed_path"] == str(processed_path)


def test_pipeline_records_lyric_processing_failure(tmp_path: Path) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_id = create_uploaded_job(database, job_dir)
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("物語\n", encoding="utf-8")
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET lyrics_path = ? WHERE id = ?",
            (str(lyrics_path), job_id),
        )

    class FailingLyricProcessor:
        def process(self, text: str) -> LyricDocument:
            raise RuntimeError("lyric formatting failed")

    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=FakeExtractor(),
        transcriber=FakeTranscriber(),
        lyric_processor=FailingLyricProcessor(),
    )

    with pytest.raises(RuntimeError, match="lyric formatting failed"):
        pipeline.process(job_id)

    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "FAILED"
    assert job["stage"] == "PROCESSING_LYRICS"
    assert job["progress"] == 75
    assert job["error_code"] == "LYRIC_PROCESSING_FAILED"
    assert job["transcript_path"] == str(job_dir / "transcript.json")


def test_pipeline_aligns_processed_lyrics_and_persists_timeline(
    tmp_path: Path,
) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_id = create_uploaded_job(database, job_dir)
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("物語\n", encoding="utf-8")
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET lyrics_path = ? WHERE id = ?",
            (str(lyrics_path), job_id),
        )

    processed = LyricDocument(
        provider="local",
        source_text="物語",
        lines=[
            LyricLine(
                source="物語",
                surface="物語",
                reading="ものがたり",
                tokens=[LyricToken(surface="物語", reading="ものがたり")],
            )
        ],
    )

    class FakeLyricProcessor:
        def process(self, text: str) -> LyricDocument:
            return processed

    class FakeAligner:
        def __init__(self) -> None:
            self.calls: list[tuple[LyricDocument, TranscriptDocument]] = []

        def align(
            self,
            lyrics: LyricDocument,
            transcript: TranscriptDocument,
        ) -> LyricTimeline:
            self.calls.append((lyrics, transcript))
            return LyricTimeline(confidence=0.9, warnings=["partial_alignment"])

    aligner = FakeAligner()
    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=FakeExtractor(),
        transcriber=FakeTranscriber(),
        lyric_processor=FakeLyricProcessor(),
        aligner=aligner,
    )

    pipeline.process(job_id)

    timeline_path = job_dir / "timeline.json"
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    assert aligner.calls[0][0] is processed
    assert timeline["confidence"] == 0.9
    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "ALIGNED"
    assert job["stage"] == "ALIGNMENT_COMPLETE"
    assert job["progress"] == 100
    assert job["timeline_path"] == str(timeline_path)


def test_pipeline_records_alignment_failure(tmp_path: Path) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_id = create_uploaded_job(database, job_dir)
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("物語\n", encoding="utf-8")
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET lyrics_path = ? WHERE id = ?",
            (str(lyrics_path), job_id),
        )

    class FakeLyricProcessor:
        def process(self, text: str) -> LyricDocument:
            return LyricDocument(provider="local", source_text=text)

    class FailingAligner:
        def align(
            self,
            lyrics: LyricDocument,
            transcript: TranscriptDocument,
        ) -> LyricTimeline:
            raise RuntimeError("alignment failed")

    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=FakeExtractor(),
        transcriber=FakeTranscriber(),
        lyric_processor=FakeLyricProcessor(),
        aligner=FailingAligner(),
    )

    with pytest.raises(RuntimeError, match="alignment failed"):
        pipeline.process(job_id)

    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "FAILED"
    assert job["stage"] == "ALIGNING"
    assert job["progress"] == 90
    assert job["error_code"] == "ALIGNMENT_FAILED"
    assert job["lyrics_processed_path"] == str(job_dir / "lyrics_processed.json")


def test_pipeline_generates_ass_after_alignment(tmp_path: Path) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_id = create_uploaded_job(database, job_dir)
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("物語\n", encoding="utf-8")
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET lyrics_path = ? WHERE id = ?",
            (str(lyrics_path), job_id),
        )

    processed = LyricDocument(provider="local", source_text="物語")
    timeline = LyricTimeline(confidence=1.0)

    class FakeLyricProcessor:
        def process(self, text: str) -> LyricDocument:
            return processed

    class FakeAligner:
        def align(
            self,
            lyrics: LyricDocument,
            transcript: TranscriptDocument,
        ) -> LyricTimeline:
            return timeline

    class FakeSubtitleGenerator:
        def __init__(self) -> None:
            self.timelines: list[LyricTimeline] = []

        def generate(self, value: LyricTimeline) -> str:
            self.timelines.append(value)
            return "[Script Info]\nScriptType: v4.00+\n"

    generator = FakeSubtitleGenerator()
    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=FakeExtractor(),
        transcriber=FakeTranscriber(),
        lyric_processor=FakeLyricProcessor(),
        aligner=FakeAligner(),
        subtitle_generator=generator,
    )

    pipeline.process(job_id)

    ass_path = job_dir / "lyrics.ass"
    assert generator.timelines == [timeline]
    assert ass_path.read_text(encoding="utf-8-sig").startswith("[Script Info]")
    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "SUBTITLE_GENERATED"
    assert job["stage"] == "SUBTITLE_GENERATION_COMPLETE"
    assert job["progress"] == 100
    assert job["ass_path"] == str(ass_path)


def test_pipeline_records_subtitle_generation_failure(tmp_path: Path) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_id = create_uploaded_job(database, job_dir)
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("物語\n", encoding="utf-8")
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET lyrics_path = ? WHERE id = ?",
            (str(lyrics_path), job_id),
        )

    class FakeLyricProcessor:
        def process(self, text: str) -> LyricDocument:
            return LyricDocument(provider="local", source_text=text)

    class FakeAligner:
        def align(
            self,
            lyrics: LyricDocument,
            transcript: TranscriptDocument,
        ) -> LyricTimeline:
            return LyricTimeline(confidence=1.0)

    class FailingSubtitleGenerator:
        def generate(self, timeline: LyricTimeline) -> str:
            raise RuntimeError("subtitle failed")

    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=FakeExtractor(),
        transcriber=FakeTranscriber(),
        lyric_processor=FakeLyricProcessor(),
        aligner=FakeAligner(),
        subtitle_generator=FailingSubtitleGenerator(),
    )

    with pytest.raises(RuntimeError, match="subtitle failed"):
        pipeline.process(job_id)

    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "FAILED"
    assert job["stage"] == "GENERATING_SUBTITLE"
    assert job["progress"] == 95
    assert job["error_code"] == "SUBTITLE_GENERATION_FAILED"
    assert job["timeline_path"] == str(job_dir / "timeline.json")


def test_pipeline_renders_final_video_after_subtitle(tmp_path: Path) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_id = create_uploaded_job(database, job_dir)
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("物語\n", encoding="utf-8")
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET lyrics_path = ? WHERE id = ?",
            (str(lyrics_path), job_id),
        )

    class FakeLyricProcessor:
        def process(self, text: str) -> LyricDocument:
            return LyricDocument(provider="local", source_text=text)

    class FakeAligner:
        def align(
            self,
            lyrics: LyricDocument,
            transcript: TranscriptDocument,
        ) -> LyricTimeline:
            return LyricTimeline(confidence=1.0)

    class FakeSubtitleGenerator:
        def generate(self, timeline: LyricTimeline) -> str:
            return "[Script Info]\nScriptType: v4.00+\n"

    class FakeVideoRenderer:
        def __init__(self) -> None:
            self.calls: list[
                tuple[Path, Path, Path, str, Path | None]
            ] = []

        def render(
            self,
            input_path: Path,
            subtitle_path: Path,
            output_path: Path,
            *,
            vocal_mode: str = "on",
            instrumental_audio_path: Path | None = None,
        ) -> None:
            self.calls.append(
                (
                    input_path,
                    subtitle_path,
                    output_path,
                    vocal_mode,
                    instrumental_audio_path,
                )
            )
            output_path.write_bytes(b"rendered-video")

    renderer = FakeVideoRenderer()
    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=FakeExtractor(),
        transcriber=FakeTranscriber(),
        lyric_processor=FakeLyricProcessor(),
        aligner=FakeAligner(),
        subtitle_generator=FakeSubtitleGenerator(),
        video_renderer=renderer,
    )

    pipeline.process(job_id)

    output_path = job_dir / "final_karaoke.mp4"
    assert renderer.calls == [
        (
            job_dir / "input.mp4",
            job_dir / "lyrics.ass",
            output_path,
            "on",
            None,
        )
    ]
    assert output_path.read_bytes() == b"rendered-video"
    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "COMPLETED"
    assert job["stage"] == "VIDEO_RENDERING_COMPLETE"
    assert job["progress"] == 100
    assert job["output_path"] == str(output_path)


def test_pipeline_records_video_rendering_failure(tmp_path: Path) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_id = create_uploaded_job(database, job_dir)
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("物語\n", encoding="utf-8")
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET lyrics_path = ? WHERE id = ?",
            (str(lyrics_path), job_id),
        )

    class FakeLyricProcessor:
        def process(self, text: str) -> LyricDocument:
            return LyricDocument(provider="local", source_text=text)

    class FakeAligner:
        def align(
            self,
            lyrics: LyricDocument,
            transcript: TranscriptDocument,
        ) -> LyricTimeline:
            return LyricTimeline(confidence=1.0)

    class FakeSubtitleGenerator:
        def generate(self, timeline: LyricTimeline) -> str:
            return "[Script Info]\n"

    class FailingVideoRenderer:
        def render(
            self,
            input_path: Path,
            subtitle_path: Path,
            output_path: Path,
            *,
            vocal_mode: str = "on",
            instrumental_audio_path: Path | None = None,
        ) -> None:
            raise RuntimeError("render failed")

    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=FakeExtractor(),
        transcriber=FakeTranscriber(),
        lyric_processor=FakeLyricProcessor(),
        aligner=FakeAligner(),
        subtitle_generator=FakeSubtitleGenerator(),
        video_renderer=FailingVideoRenderer(),
    )

    with pytest.raises(RuntimeError, match="render failed"):
        pipeline.process(job_id)

    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "FAILED"
    assert job["stage"] == "RENDERING_VIDEO"
    assert job["progress"] == 98
    assert job["error_code"] == "VIDEO_RENDERING_FAILED"
    assert job["ass_path"] == str(job_dir / "lyrics.ass")


def test_pipeline_does_not_expose_raw_exception_details(tmp_path: Path) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_id = create_uploaded_job(database, job_dir)

    class SecretFailingTranscriber:
        def transcribe(self, audio_path: Path) -> TranscriptDocument:
            raise RuntimeError("secret-token=C:/private/model")

    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=FakeExtractor(),
        transcriber=SecretFailingTranscriber(),
    )

    with pytest.raises(RuntimeError):
        pipeline.process(job_id)

    job = database.get_job(job_id)
    assert job is not None
    assert "secret-token" not in job["error_message"]
    assert "private" not in job["error_message"]
    assert job["error_message"] == (
        "Processing failed during audio transcription. "
        "Check server logs with this job ID."
    )
