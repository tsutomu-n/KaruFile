"""Typed values passed through the video pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from pathlib import Path
from typing import Any


class Preset(StrEnum):
    STANDARD = "standard"
    COMPACT = "compact"


class ProcessStatus(StrEnum):
    ADOPTED = "ADOPTED"
    UNCHANGED = "UNCHANGED"
    SKIPPED_STANDARD = "SKIPPED_STANDARD"
    SKIPPED_COMPLEX = "SKIPPED_COMPLEX"
    SKIPPED_UNSUPPORTED = "SKIPPED_UNSUPPORTED"
    SKIPPED_COMPLETE = "SKIPPED_COMPLETE"
    DRY_RUN = "DRY_RUN"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class FileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    path: Path
    relative_path: Path
    sha256: str
    identity: FileIdentity

    @property
    def size(self) -> int:
        return self.identity.size

    @property
    def mtime_ns(self) -> int:
        return self.identity.mtime_ns

    def output_path(self, output_root: Path) -> Path:
        return output_root / self.relative_path


@dataclass(frozen=True, slots=True)
class StreamInfo:
    index: int
    codec_type: str
    codec_name: str = ""
    profile: str = ""
    width: int | None = None
    height: int | None = None
    pix_fmt: str = ""
    field_order: str = ""
    sample_aspect_ratio: str = ""
    r_frame_rate: Fraction | None = None
    avg_frame_rate: Fraction | None = None
    color_primaries: str = ""
    color_transfer: str = ""
    color_space: str = ""
    bits_per_raw_sample: int | None = None
    channels: int | None = None
    sample_rate: int | None = None
    bit_rate: int | None = None
    duration: float | None = None
    disposition: dict[str, int] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    side_data: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class MediaInfo:
    path: Path
    format_name: str
    duration: float
    streams: tuple[StreamInfo, ...]
    chapter_count: int = 0

    @property
    def video_streams(self) -> tuple[StreamInfo, ...]:
        return tuple(stream for stream in self.streams if stream.codec_type == "video")

    @property
    def audio_streams(self) -> tuple[StreamInfo, ...]:
        return tuple(stream for stream in self.streams if stream.codec_type == "audio")


@dataclass(frozen=True, slots=True)
class Eligibility:
    eligible: bool
    status: ProcessStatus | None
    reason: str
    video: StreamInfo | None = None
    audio: StreamInfo | None = None
    rotation: int = 0
    display_width: int = 0
    display_height: int = 0
    target_width: int = 0
    target_height: int = 0
    source_fps: Fraction | None = None
    target_fps: Fraction | None = None
    duration: float = 0.0


@dataclass(frozen=True, slots=True)
class ToolInfo:
    ffmpeg: Path
    ffprobe: Path
    ffmpeg_version: str
    ffprobe_version: str


@dataclass(frozen=True, slots=True)
class QualityResult:
    mean: float
    p5: float
    frame_count: int


@dataclass(frozen=True, slots=True)
class ProcessResult:
    source_path: str
    source_size: int
    output_path: str
    output_size: int | None
    saved_bytes: int
    saved_percent: float
    status: ProcessStatus
    error_message: str
    preset: Preset
    source_sha256: str
    output_sha256: str = ""
    reason: str = ""
    video_codec: str = ""
    audio_codec: str = ""
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    duration: float | None = None
    vmaf_mean: float | None = None
    vmaf_p5: float | None = None
    ffmpeg_version: str = ""
    output_identity: FileIdentity | None = None

    def as_csv_row(self) -> dict[str, object]:
        return {
            "source_path": self.source_path,
            "source_size": self.source_size,
            "output_path": self.output_path,
            "output_size": "" if self.output_size is None else self.output_size,
            "saved_bytes": self.saved_bytes,
            "saved_percent": f"{self.saved_percent:.6f}",
            "status": self.status.value,
            "error_message": self.error_message,
            "preset": self.preset.value,
            "source_sha256": self.source_sha256,
            "output_sha256": self.output_sha256,
            "reason": self.reason,
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "width": "" if self.width is None else self.width,
            "height": "" if self.height is None else self.height,
            "fps": "" if self.fps is None else f"{self.fps:.6f}",
            "duration": "" if self.duration is None else f"{self.duration:.6f}",
            "vmaf_mean": "" if self.vmaf_mean is None else f"{self.vmaf_mean:.6f}",
            "vmaf_p5": "" if self.vmaf_p5 is None else f"{self.vmaf_p5:.6f}",
            "ffmpeg_version": self.ffmpeg_version,
        }
