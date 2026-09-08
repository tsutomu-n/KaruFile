"""SQLite state used for safe resumability."""
from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import CompactRecipe
from .models import Preset, ProcessResult, ProcessStatus, SourceSnapshot
from .utils import stable_sha256_file


REUSABLE_STATUSES = frozenset(
    {
        ProcessStatus.ADOPTED,
        ProcessStatus.UNCHANGED,
        ProcessStatus.SKIPPED_STANDARD,
        ProcessStatus.SKIPPED_COMPLEX,
        ProcessStatus.SKIPPED_UNSUPPORTED,
    }
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    source_path TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL,
    source_size INTEGER NOT NULL,
    source_mtime_ns INTEGER NOT NULL,
    config_hash TEXT NOT NULL,
    output_path TEXT NOT NULL,
    output_size INTEGER,
    output_sha256 TEXT,
    saved_bytes INTEGER NOT NULL,
    saved_percent REAL NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT NOT NULL,
    preset TEXT NOT NULL,
    reason TEXT NOT NULL,
    video_codec TEXT NOT NULL,
    audio_codec TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    fps REAL,
    duration REAL,
    vmaf_mean REAL,
    vmaf_p5 REAL,
    ffmpeg_version TEXT NOT NULL,
    processed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_video_status ON files(status);
"""


@dataclass(frozen=True, slots=True)
class Record:
    source_path: str
    source_sha256: str
    source_size: int
    source_mtime_ns: int
    config_hash: str
    output_path: str
    output_size: int | None
    output_sha256: str
    saved_bytes: int
    saved_percent: float
    status: str
    error_message: str
    preset: str
    reason: str
    video_codec: str
    audio_codec: str
    width: int | None
    height: int | None
    fps: float | None
    duration: float | None
    vmaf_mean: float | None
    vmaf_p5: float | None
    ffmpeg_version: str


def init_db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30.0)
    connection.executescript(SCHEMA)
    connection.commit()
    connection.row_factory = sqlite3.Row
    return connection


def get_record(connection: sqlite3.Connection, source_path: str) -> Record | None:
    row = connection.execute("SELECT * FROM files WHERE source_path = ?", (source_path,)).fetchone()
    if row is None:
        return None
    values = dict(row)
    values.pop("processed_at", None)
    values["output_sha256"] = values.get("output_sha256") or ""
    return Record(**values)


def reusable_result(
    record: Record | None,
    source: SourceSnapshot,
    config_hash: str,
    *,
    expected_destination: Path,
    expected_preset: Preset,
    recipe: CompactRecipe,
    dry_run: bool,
) -> ProcessResult | None:
    if dry_run or record is None:
        return None

    try:
        status = ProcessStatus(record.status)
        preset = Preset(record.preset)
    except (TypeError, ValueError):
        return None
    if status not in REUSABLE_STATUSES or preset is not expected_preset:
        return None
    if status is ProcessStatus.SKIPPED_STANDARD and preset is not Preset.STANDARD:
        return None
    if status is not ProcessStatus.SKIPPED_STANDARD and preset is not Preset.COMPACT:
        return None

    def path_key(path: str | os.PathLike[str]) -> str:
        return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(path))))

    try:
        if path_key(record.source_path) != path_key(source.path):
            return None
        if path_key(record.output_path) != path_key(expected_destination):
            return None
    except (OSError, TypeError, ValueError):
        return None

    if (
        record.source_sha256 != source.sha256
        or record.source_size != source.size
        or record.config_hash != config_hash
    ):
        return None
    if not isinstance(record.output_size, int) or isinstance(record.output_size, bool):
        return None
    if record.output_size < 0:
        return None
    if not isinstance(record.saved_bytes, int) or isinstance(record.saved_bytes, bool):
        return None
    expected_saved = source.size - record.output_size
    if record.saved_bytes != expected_saved or expected_saved < 0:
        return None
    if status is ProcessStatus.ADOPTED:
        if (
            source.size <= 0
            or expected_saved < recipe.min_saved_bytes
            or expected_saved / source.size < recipe.min_saved_percent
        ):
            return None
    elif record.output_size != source.size or expected_saved != 0:
        return None
    try:
        saved_percent = float(record.saved_percent)
    except (TypeError, ValueError):
        return None
    expected_percent = expected_saved / source.size * 100 if source.size else 0.0
    if not math.isfinite(saved_percent) or not math.isclose(
        saved_percent, expected_percent, rel_tol=1e-12, abs_tol=1e-9
    ):
        return None
    if (
        not isinstance(record.output_sha256, str)
        or len(record.output_sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in record.output_sha256)
    ):
        return None
    if record.error_message:
        return None

    for value in (record.width, record.height):
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
        ):
            return None
    for value in (record.fps, record.duration):
        if value is not None:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(numeric) or numeric <= 0:
                return None
    for value in (record.vmaf_mean, record.vmaf_p5):
        if value is not None:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(numeric) or not 0 <= numeric <= 100:
                return None
    if status is ProcessStatus.ADOPTED and (
        record.width is None
        or record.height is None
        or record.fps is None
        or record.duration is None
        or record.vmaf_mean is None
        or record.vmaf_p5 is None
    ):
        return None
    if status is ProcessStatus.ADOPTED and str(record.video_codec).casefold() != "av1":
        return None
    if status is ProcessStatus.ADOPTED:
        if (
            record.width > recipe.max_width
            or record.height > recipe.max_height
            or record.width % 2
            or record.height % 2
            or float(record.fps) > recipe.max_fps
            or float(record.vmaf_mean) < recipe.vmaf_min_mean
            or float(record.vmaf_p5) < recipe.vmaf_min_p5
            or not record.ffmpeg_version
        ):
            return None
        expected_audio_codecs = (
            {"", "aac"}
            if expected_destination.suffix.casefold() in {".mp4", ".m4v"}
            else {"", "opus"}
        )
        if str(record.audio_codec).casefold() not in expected_audio_codecs:
            return None
    elif record.output_sha256.casefold() != source.sha256.casefold():
        return None

    output = expected_destination
    try:
        if not output.is_file():
            return None
        output_sha256, output_identity = stable_sha256_file(output)
        if (
            output_identity.size != record.output_size
            or output_sha256.casefold() != record.output_sha256.casefold()
        ):
            return None
    except OSError:
        return None
    return ProcessResult(
        source_path=str(source.path),
        source_size=source.size,
        output_path=str(expected_destination),
        output_size=record.output_size,
        saved_bytes=expected_saved,
        saved_percent=expected_percent,
        status=ProcessStatus.SKIPPED_COMPLETE,
        error_message="",
        preset=expected_preset,
        source_sha256=source.sha256,
        output_sha256=record.output_sha256.casefold(),
        reason=f"reused {status.value}",
        video_codec=record.video_codec,
        audio_codec=record.audio_codec,
        width=record.width,
        height=record.height,
        fps=float(record.fps) if record.fps is not None else None,
        duration=float(record.duration) if record.duration is not None else None,
        vmaf_mean=float(record.vmaf_mean) if record.vmaf_mean is not None else None,
        vmaf_p5=float(record.vmaf_p5) if record.vmaf_p5 is not None else None,
        ffmpeg_version=record.ffmpeg_version,
        output_identity=output_identity,
    )


def save_result(
    connection: sqlite3.Connection,
    source: SourceSnapshot,
    result: ProcessResult,
    config_hash: str,
    *,
    commit: bool = True,
) -> None:
    def path_key(path: str | os.PathLike[str]) -> str:
        return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(path))))

    if path_key(result.source_path) != path_key(source.path):
        raise ValueError("state result source_path does not match its snapshot")
    if (
        result.source_size != source.size
        or result.source_sha256.casefold() != source.sha256.casefold()
    ):
        raise ValueError("state result source identity does not match its snapshot")
    source_sha256, _source_identity = stable_sha256_file(
        source.path,
        expected_identity=source.identity,
    )
    if source_sha256.casefold() != source.sha256.casefold():
        raise OSError(f"source changed before state save: {source.path}")
    if result.output_size is None:
        if result.output_sha256:
            raise ValueError("state result without output_size must not have output_sha256")
    else:
        if not result.output_sha256:
            raise ValueError("state result with output_size must have output_sha256")
        if result.output_identity is None:
            raise ValueError("state result with output_size must have output identity")
        output_sha256, output_identity = stable_sha256_file(
            Path(result.output_path),
            expected_identity=result.output_identity,
        )
        if (
            output_identity.size != result.output_size
            or output_sha256.casefold() != result.output_sha256.casefold()
        ):
            raise OSError(f"output changed before state save: {result.output_path}")
    connection.execute(
        """
        INSERT INTO files (
            source_path, source_sha256, source_size, source_mtime_ns, config_hash,
            output_path, output_size, output_sha256, saved_bytes, saved_percent,
            status, error_message, preset, reason, video_codec, audio_codec,
            width, height, fps, duration, vmaf_mean, vmaf_p5, ffmpeg_version, processed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source_path) DO UPDATE SET
            source_sha256=excluded.source_sha256,
            source_size=excluded.source_size,
            source_mtime_ns=excluded.source_mtime_ns,
            config_hash=excluded.config_hash,
            output_path=excluded.output_path,
            output_size=excluded.output_size,
            output_sha256=excluded.output_sha256,
            saved_bytes=excluded.saved_bytes,
            saved_percent=excluded.saved_percent,
            status=excluded.status,
            error_message=excluded.error_message,
            preset=excluded.preset,
            reason=excluded.reason,
            video_codec=excluded.video_codec,
            audio_codec=excluded.audio_codec,
            width=excluded.width,
            height=excluded.height,
            fps=excluded.fps,
            duration=excluded.duration,
            vmaf_mean=excluded.vmaf_mean,
            vmaf_p5=excluded.vmaf_p5,
            ffmpeg_version=excluded.ffmpeg_version,
            processed_at=excluded.processed_at
        """,
        (
            str(source.path),
            source.sha256,
            source.size,
            source.mtime_ns,
            config_hash,
            result.output_path,
            result.output_size,
            result.output_sha256,
            result.saved_bytes,
            result.saved_percent,
            result.status.value,
            result.error_message,
            result.preset.value,
            result.reason,
            result.video_codec,
            result.audio_codec,
            result.width,
            result.height,
            result.fps,
            result.duration,
            result.vmaf_mean,
            result.vmaf_p5,
            result.ffmpeg_version,
            dt.datetime.now(dt.timezone.utc).isoformat(),
        ),
    )
    if commit:
        connection.commit()
