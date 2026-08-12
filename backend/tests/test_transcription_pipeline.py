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
from app.alignment.models import AlignedLine, AlignedToken, LyricTimeline
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
        "服务器未能生成歌声时间信息。请使用任务 ID 查询语音分析日志。"
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


def test_pipeline_pauses_for_reading_review_before_alignment(
    tmp_path: Path,
) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "reading-review"
    job_id = create_uploaded_job(database, job_dir)
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("物语\n", encoding="utf-8")
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET lyrics_path = ? WHERE id = ?",
            (str(lyrics_path), job_id),
        )

    class FakeLyricProcessor:
        def process(self, text: str) -> LyricDocument:
            return LyricDocument(
                provider="local",
                source_text=text,
                lines=[
                    LyricLine(
                        source="物语",
                        surface="物语",
                        reading="ものがたり",
                        tokens=[
                            LyricToken(
                                surface="物语",
                                reading="ものがたり",
                            )
                        ],
                    )
                ],
            )

    class UnexpectedAligner:
        requires_reading_review = True

        def align(self, *args, **kwargs) -> LyricTimeline:
            pytest.fail("alignment must wait for reading confirmation")

    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=FakeExtractor(),
        transcriber=FakeTranscriber(),
        lyric_processor=FakeLyricProcessor(),
        aligner=UnexpectedAligner(),
    )

    pipeline.process(job_id)

    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "LYRICS_PROCESSED"
    assert job["stage"] == "READING_REVIEW_REQUIRED"
    assert job["progress"] == 80
    assert job["lyrics_processed_path"] == str(
        job_dir / "lyrics_processed.json"
    )
    assert not (job_dir / "timeline.json").exists()


def test_pipeline_resumes_with_reviewed_readings_without_repeating_audio_work(
    tmp_path: Path,
) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "reviewed-alignment"
    job_id = create_uploaded_job(database, job_dir)
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("君\n", encoding="utf-8")
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET lyrics_path = ? WHERE id = ?",
            (str(lyrics_path), job_id),
        )

    class FakeLyricProcessor:
        def process(self, text: str) -> LyricDocument:
            return LyricDocument(
                provider="local",
                source_text=text,
                lines=[
                    LyricLine(
                        source="君",
                        surface="君",
                        reading="くん",
                        tokens=[LyricToken(surface="君", reading="くん")],
                    )
                ],
            )

    class RecordingAligner:
        requires_reading_review = True

        def __init__(self) -> None:
            self.readings: list[str] = []

        def align(
            self,
            lyrics: LyricDocument,
            transcript: TranscriptDocument,
        ) -> LyricTimeline:
            self.readings.append(lyrics.lines[0].tokens[0].reading)
            return LyricTimeline(confidence=1.0)

    extractor = FakeExtractor()
    transcriber = FakeTranscriber()
    aligner = RecordingAligner()
    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=extractor,
        transcriber=transcriber,
        lyric_processor=FakeLyricProcessor(),
        aligner=aligner,
    )

    pipeline.process(job_id)
    assert aligner.readings == []

    processed_path = job_dir / "lyrics_processed.json"
    reviewed = json.loads(processed_path.read_text(encoding="utf-8"))
    reviewed["lines"][0]["reading"] = "きみ"
    reviewed["lines"][0]["tokens"][0]["reading"] = "きみ"
    processed_path.write_text(
        json.dumps(reviewed, ensure_ascii=False),
        encoding="utf-8",
    )
    assert database.claim_reading_review(job_id)
    assert database.queue_alignment(job_id)

    pipeline.process(job_id)

    assert extractor.calls == [(job_dir / "input.mp4", job_dir / "audio.wav")]
    assert transcriber.calls == [job_dir / "audio.wav"]
    assert aligner.readings == ["きみ"]
    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "ALIGNED"
    assert job["stage"] == "ALIGNMENT_COMPLETE"


def test_pipeline_uses_existing_lrc_text_and_line_timing(tmp_path: Path) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_id = create_uploaded_job(database, job_dir)
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text(
        "[00:01.00]{今日|きょう}も\n[00:03.50]歌う\n",
        encoding="utf-8",
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET lyrics_path = ? WHERE id = ?",
            (str(lyrics_path), job_id),
        )

    processed = LyricDocument(
        provider="local",
        source_text="今日も\n歌う",
        lines=[
            LyricLine(
                source="今日も",
                surface="今日も",
                reading="きょうも",
                tokens=[LyricToken(surface="今日も", reading="きょうも")],
            ),
            LyricLine(
                source="歌う",
                surface="歌う",
                reading="うたう",
                tokens=[LyricToken(surface="歌う", reading="うたう")],
            ),
        ],
    )

    class RecordingLyricProcessor:
        def __init__(self) -> None:
            self.texts: list[str] = []

        def process(self, text: str) -> LyricDocument:
            self.texts.append(text)
            return processed

    class FixedAligner:
        def align(
            self,
            lyrics: LyricDocument,
            transcript: TranscriptDocument,
        ) -> LyricTimeline:
            return LyricTimeline(
                confidence=1.0,
                lines=[
                    AlignedLine(
                        surface=line.surface,
                        reading=line.reading,
                        start_ms=2000 + index * 2000,
                        end_ms=3000 + index * 2000,
                        confidence=1.0,
                        tokens=[
                            AlignedToken(
                                surface=line.surface,
                                reading=line.reading,
                                start_ms=2000 + index * 2000,
                                end_ms=3000 + index * 2000,
                                confidence=1.0,
                            )
                        ],
                    )
                    for index, line in enumerate(lyrics.lines)
                ],
            )

    lyric_processor = RecordingLyricProcessor()
    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=FakeExtractor(),
        transcriber=FakeTranscriber(),
        lyric_processor=lyric_processor,
        aligner=FixedAligner(),
    )

    pipeline.process(job_id)

    assert lyric_processor.texts == ["今日も\n歌う"]
    timeline = json.loads(
        (job_dir / "timeline.json").read_text(encoding="utf-8")
    )
    assert [
        (line["start_ms"], line["end_ms"]) for line in timeline["lines"]
    ] == [(1000, 3500), (3500, 4500)]
    assert "lrc_timing_applied" in timeline["warnings"]


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
    assert "备用时间轴" in job["error_message"]
    assert "Whisper" not in job["error_message"]
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


def test_audio_only_pipeline_stops_after_subtitle_generation(
    tmp_path: Path,
) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "audio-job"
    job_dir.mkdir(parents=True)
    source_audio = job_dir / "input_audio.wav"
    source_audio.write_bytes(b"source-audio")
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("物語\n", encoding="utf-8")
    job_id = "42adf1aa-717f-4ed8-8ec8-3b7d8d153989"
    database.create_job(
        job_id=job_id,
        original_video_name="song.mp4",
        video_size_bytes=100 * 1024 * 1024,
        video_sha256="audio-sha",
        video_path=source_audio,
        lyrics_source="text",
        lyrics_path=lyrics_path,
        input_mode="AUDIO_ONLY",
        source_upload_size_bytes=len(b"source-audio"),
        source_upload_sha256="audio-sha",
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

    class UnexpectedVideoRenderer:
        def render(self, *args, **kwargs) -> None:
            pytest.fail("audio-only jobs must not render video on the server")

    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=FakeExtractor(),
        transcriber=FakeTranscriber(),
        lyric_processor=FakeLyricProcessor(),
        aligner=FakeAligner(),
        subtitle_generator=FakeSubtitleGenerator(),
        video_renderer=UnexpectedVideoRenderer(),
    )

    pipeline.process(job_id)

    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "SUBTITLE_GENERATED"
    assert job["stage"] == "SUBTITLE_GENERATION_COMPLETE"
    assert job["ass_path"] == str(job_dir / "lyrics.ass")
    assert job["output_path"] is None


def test_audio_only_high_accuracy_pipeline_runs_uvr_once_and_uses_vocals(
    tmp_path: Path,
) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "audio-job-high-accuracy"
    job_dir.mkdir(parents=True)
    source_audio = job_dir / "input_audio.m4a"
    source_audio.write_bytes(b"source-audio")
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("物語\n", encoding="utf-8")
    job_id = "8d517cd1-e9b8-485b-ad5b-bd766a6fb951"
    database.create_job(
        job_id=job_id,
        original_video_name="song.mp4",
        video_size_bytes=100,
        video_sha256="audio-sha",
        video_path=source_audio,
        lyrics_source="text",
        lyrics_path=lyrics_path,
        input_mode="AUDIO_ONLY",
        source_upload_size_bytes=len(b"source-audio"),
        source_upload_sha256="audio-sha",
    )

    class StereoExtractor(FakeExtractor):
        def extract_stereo(self, input_path: Path, output_path: Path) -> None:
            output_path.write_bytes(b"stereo")

    class StemSeparator:
        def __init__(self) -> None:
            self.calls = []

        def separate_stems(
            self,
            input_path: Path,
            vocals_path: Path,
            instrumental_path: Path,
        ) -> None:
            self.calls.append((input_path, vocals_path, instrumental_path))
            vocals_path.write_bytes(b"vocals")
            instrumental_path.write_bytes(b"instrumental")

    class LyricProcessor:
        def process(self, text: str) -> LyricDocument:
            return LyricDocument(
                provider="local",
                source_text=text,
                lines=[
                    LyricLine(
                        source="物語",
                        surface="物語",
                        reading="ものがたり",
                        tokens=[
                            LyricToken(surface="物語", reading="ものがたり")
                        ],
                    )
                ],
            )

    class AudioAwareAligner:
        requires_vocals = True
        supports_transcriptless_alignment = True

        def __init__(self) -> None:
            self.audio_paths: list[Path] = []

        def align(
            self,
            lyrics,
            transcript,
            *,
            audio_path,
            transcript_factory,
        ):
            assert transcript is None
            self.audio_paths.append(audio_path)
            return LyricTimeline(
                confidence=1.0,
                alignment_engine="fa_kara_mms",
            )

    class SubtitleGenerator:
        def generate(self, timeline: LyricTimeline) -> str:
            return "[Script Info]\n"

    separator = StemSeparator()
    transcriber = FakeTranscriber()
    aligner = AudioAwareAligner()
    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=StereoExtractor(),
        transcriber=transcriber,
        vocal_remover=separator,
        lyric_processor=LyricProcessor(),
        aligner=aligner,
        subtitle_generator=SubtitleGenerator(),
    )

    pipeline.process(job_id)

    vocals_path = job_dir / "audio_vocals.wav"
    instrumental_path = job_dir / "audio_instrumental.wav"
    assert separator.calls == [
        (job_dir / "audio_stereo.wav", vocals_path, instrumental_path)
    ]
    assert transcriber.calls == []
    assert not (job_dir / "transcript.json").exists()
    assert aligner.audio_paths == [vocals_path]
    timeline = json.loads((job_dir / "timeline.json").read_text(encoding="utf-8"))
    assert timeline["alignment_engine"] == "fa_kara_mms"


def test_audio_only_pipeline_uses_fallback_when_vocal_stem_is_unavailable(
    tmp_path: Path,
) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "audio-job-no-vocal-stem"
    job_dir.mkdir(parents=True)
    source_audio = job_dir / "input_audio.m4a"
    source_audio.write_bytes(b"source-audio")
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("物語\n", encoding="utf-8")
    job_id = "aabcc5e6-e31e-4f32-a6b5-f58414ab7814"
    database.create_job(
        job_id=job_id,
        original_video_name="song.mp4",
        video_size_bytes=100,
        video_sha256="audio-sha",
        video_path=source_audio,
        lyrics_source="text",
        lyrics_path=lyrics_path,
        input_mode="AUDIO_ONLY",
    )

    class InstrumentalOnlyRemover:
        def remove_vocals(self, input_path: Path, output_path: Path) -> None:
            pytest.fail("ON VOCAL fallback must not run instrumental-only UVR")

    class LyricProcessor:
        def process(self, text: str) -> LyricDocument:
            return LyricDocument(provider="local", source_text=text)

    class OptionalAudioAligner:
        requires_vocals = True
        supports_transcriptless_alignment = True

        def __init__(self) -> None:
            self.audio_paths = []

        def align(
            self,
            lyrics,
            transcript,
            *,
            audio_path=None,
            transcript_factory=None,
        ):
            assert transcript is not None
            self.audio_paths.append(audio_path)
            return LyricTimeline(
                confidence=0.5,
                alignment_engine="whisper_mora",
            )

    aligner = OptionalAudioAligner()
    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=FakeExtractor(),
        transcriber=FakeTranscriber(),
        vocal_remover=InstrumentalOnlyRemover(),
        lyric_processor=LyricProcessor(),
        aligner=aligner,
    )

    pipeline.process(job_id)

    assert aligner.audio_paths == [None]
    assert pipeline.transcriber.calls == [job_dir / "audio.wav"]
    timeline = json.loads((job_dir / "timeline.json").read_text(encoding="utf-8"))
    assert timeline["warnings"] == ["uvr_unavailable"]


def test_audio_only_pipeline_falls_back_when_vocal_separation_fails(
    tmp_path: Path,
) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "audio-job-uvr-failure"
    job_dir.mkdir(parents=True)
    source_audio = job_dir / "input_audio.m4a"
    source_audio.write_bytes(b"source-audio")
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("物語\n", encoding="utf-8")
    job_id = "5c4845ab-6d9d-4b68-86b0-a47b77714d5d"
    database.create_job(
        job_id=job_id,
        original_video_name="song.m4a",
        video_size_bytes=100,
        video_sha256="audio-sha",
        video_path=source_audio,
        lyrics_source="text",
        lyrics_path=lyrics_path,
        input_mode="AUDIO_ONLY",
    )

    class StereoExtractor(FakeExtractor):
        def extract_stereo(self, input_path: Path, output_path: Path) -> None:
            output_path.write_bytes(b"stereo")

    class FailingSeparator:
        def separate_stems(
            self,
            input_path: Path,
            vocals_path: Path,
            instrumental_path: Path,
        ) -> None:
            raise RuntimeError("model unavailable")

    class LyricProcessor:
        def process(self, text: str) -> LyricDocument:
            return LyricDocument(provider="local", source_text=text)

    class OptionalAudioAligner:
        requires_vocals = True
        supports_transcriptless_alignment = True

        def __init__(self) -> None:
            self.audio_paths = []

        def align(
            self,
            lyrics,
            transcript,
            *,
            audio_path=None,
            transcript_factory=None,
        ):
            assert transcript is not None
            self.audio_paths.append(audio_path)
            return LyricTimeline(
                confidence=0.5,
                alignment_engine="whisper_mora",
            )

    transcriber = FakeTranscriber()
    aligner = OptionalAudioAligner()
    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=StereoExtractor(),
        transcriber=transcriber,
        vocal_remover=FailingSeparator(),
        lyric_processor=LyricProcessor(),
        aligner=aligner,
    )

    pipeline.process(job_id)

    assert transcriber.calls == [job_dir / "audio.wav"]
    assert aligner.audio_paths == [None]
    timeline = json.loads((job_dir / "timeline.json").read_text(encoding="utf-8"))
    assert timeline["warnings"] == ["uvr_fallback:RuntimeError"]


def test_cloud_render_queue_skips_recognition_and_only_renders_video(
    tmp_path: Path,
) -> None:
    pipeline_module = importlib.import_module("app.tasks.pipeline")
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "cloud-render"
    job_dir.mkdir(parents=True)
    video_path = job_dir / "input.mp4"
    video_path.write_bytes(b"video")
    timeline_path = job_dir / "timeline.json"
    timeline_path.write_text('{"confidence":1,"lines":[],"warnings":[]}', encoding="utf-8")
    ass_path = job_dir / "lyrics.ass"
    ass_path.write_text("[Script Info]\n", encoding="utf-8")
    job_id = "52adf1aa-717f-4ed8-8ec8-3b7d8d153989"
    database.create_job(
        job_id=job_id,
        original_video_name="song.mp4",
        video_size_bytes=100,
        video_sha256="video-sha",
        video_path=video_path,
        lyrics_source="text",
        lyrics_path=None,
        input_mode="AUDIO_ONLY",
    )
    database.update_job_state(
        job_id,
        status="UPLOADED",
        stage="CLOUD_RENDER_QUEUED",
        progress=0,
        timeline_path=timeline_path,
        ass_path=ass_path,
    )

    class UnexpectedProcessor:
        def __getattr__(self, name):
            pytest.fail(f"cloud render must not call recognition step: {name}")

    class RecordingRenderer:
        def __init__(self) -> None:
            self.calls = []
            self.progress_during_render = []

        def render(self, input_path, subtitle_path, output_path, **kwargs) -> None:
            self.calls.append((input_path, subtitle_path, kwargs))
            current = database.get_job(job_id)
            assert current is not None
            self.progress_during_render.append(current["progress"])
            output_path.write_bytes(b"rendered")

    renderer = RecordingRenderer()
    pipeline = pipeline_module.TranscriptionPipeline(
        database=database,
        extractor=UnexpectedProcessor(),
        transcriber=UnexpectedProcessor(),
        video_renderer=renderer,
    )

    pipeline.process(job_id)

    assert renderer.calls == [(video_path, ass_path, {"vocal_mode": "on", "instrumental_audio_path": None})]
    assert renderer.progress_during_render == [50]
    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "COMPLETED"
    assert job["stage"] == "VIDEO_RENDERING_COMPLETE"


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
        "服务器未能生成歌声时间信息。请使用任务 ID 查询语音分析日志。"
    )
