"""Typed video presets and processing identity."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import Preset, ToolInfo


SUPPORTED_EXTENSIONS = frozenset({".mp4", ".m4v", ".mkv", ".webm"})


@dataclass(frozen=True, slots=True)
class CompactRecipe:
    max_width: int = 1280
    max_height: int = 720
    max_fps: int = 30
    crf_ladder: tuple[int, ...] = (38, 35, 32)
    encoder_preset: int = 8
    audio_bitrate_mono: int = 64_000
    audio_bitrate_stereo: int = 96_000
    vmaf_model: str = "vmaf_v0.6.1"
    vmaf_subsample: int = 5
    vmaf_min_mean: float = 85.0
    vmaf_min_p5: float = 70.0
    min_saved_bytes: int = 1024 * 1024
    min_saved_percent: float = 0.10
    duration_tolerance_seconds: float = 0.25
    probe_timeout_seconds: float = 30.0
    tool_timeout_seconds: float = 15.0
    encode_timeout_base_seconds: float = 300.0
    encode_timeout_per_media_second: float = 60.0
    encode_timeout_max_seconds: float = 6 * 60 * 60.0
    validation_timeout_base_seconds: float = 120.0
    validation_timeout_per_media_second: float = 10.0
    validation_timeout_max_seconds: float = 2 * 60 * 60.0
    max_subprocess_output_bytes: int = 1024 * 1024
    max_vmaf_log_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_width < 2 or self.max_height < 2 or self.max_fps < 1:
            raise ValueError("video dimensions and fps must be positive")
        if not self.crf_ladder or any(crf < 0 or crf > 63 for crf in self.crf_ladder):
            raise ValueError("crf_ladder values must be between 0 and 63")
        if any(left <= right for left, right in zip(self.crf_ladder, self.crf_ladder[1:])):
            raise ValueError("crf_ladder must be strictly descending")
        if self.encoder_preset < 0 or self.encoder_preset > 13:
            raise ValueError("encoder_preset must be between 0 and 13")
        if self.audio_bitrate_mono <= 0 or self.audio_bitrate_stereo <= 0:
            raise ValueError("audio bitrates must be positive")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", self.vmaf_model):
            raise ValueError("vmaf_model contains unsupported characters")
        if not 0 <= self.vmaf_min_mean <= 100 or not 0 <= self.vmaf_min_p5 <= 100:
            raise ValueError("VMAF thresholds must be between 0 and 100")
        if self.vmaf_min_mean < self.vmaf_min_p5:
            raise ValueError("VMAF mean threshold must not be below p5")
        if self.min_saved_bytes < 0 or not 0 <= self.min_saved_percent <= 1:
            raise ValueError("savings thresholds are invalid")
        if self.duration_tolerance_seconds < 0:
            raise ValueError("duration tolerance must not be negative")
        if any(
            value <= 0
            for value in (
                self.probe_timeout_seconds,
                self.tool_timeout_seconds,
                self.encode_timeout_base_seconds,
                self.encode_timeout_max_seconds,
                self.validation_timeout_base_seconds,
                self.validation_timeout_max_seconds,
                self.max_subprocess_output_bytes,
                self.max_vmaf_log_bytes,
            )
        ):
            raise ValueError("timeouts and output limit must be positive")
        if self.encode_timeout_per_media_second < 0 or self.validation_timeout_per_media_second < 0:
            raise ValueError("per-media timeout factors must not be negative")
        if self.encode_timeout_base_seconds > self.encode_timeout_max_seconds:
            raise ValueError("encode timeout maximum must cover its base")
        if self.validation_timeout_base_seconds > self.validation_timeout_max_seconds:
            raise ValueError("validation timeout maximum must cover its base")
        if self.vmaf_subsample < 1:
            raise ValueError("vmaf_subsample must be positive")

    def encode_timeout(self, duration: float) -> float:
        return min(
            self.encode_timeout_max_seconds,
            max(self.encode_timeout_base_seconds, duration * self.encode_timeout_per_media_second),
        )

    def validation_timeout(self, duration: float) -> float:
        return min(
            self.validation_timeout_max_seconds,
            max(
                self.validation_timeout_base_seconds,
                duration * self.validation_timeout_per_media_second,
            ),
        )


@dataclass(frozen=True, slots=True)
class VideoConfig:
    input_dir: Path
    output_dir: Path
    preset: Preset = Preset.STANDARD
    workers: int = 1
    dry_run: bool = False
    ffmpeg_path: Path | None = None
    ffprobe_path: Path | None = None
    recipe: CompactRecipe = CompactRecipe()
    safe: bool = False
    remove_audio: bool = False

    def __post_init__(self) -> None:
        if self.workers < 1:
            raise ValueError("--workers must be at least 1")
        if self.preset is not Preset.COMPACT and (self.safe or self.remove_audio):
            raise ValueError("--safe and --remove-audio require --preset compact")

    def processing_hash(self, tools: ToolInfo | None) -> str:
        relevant = {
            "algorithm": "video-shrink-v2",
            "safe": self.safe,
            "remove_audio": self.remove_audio,
            "output_dir": str(self.output_dir),
            "preset": self.preset.value,
            "dry_run": self.dry_run,
            "recipe": asdict(self.recipe),
            "ffmpeg_path": str(tools.ffmpeg) if tools else "",
            "ffprobe_path": str(tools.ffprobe) if tools else "",
            "ffmpeg_version": tools.ffmpeg_version if tools else "",
            "ffprobe_version": tools.ffprobe_version if tools else "",
        }
        encoded = json.dumps(relevant, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def report_path(output_dir: Path, *, dry_run: bool) -> Path:
    suffix = ".video-report.dry-run.csv" if dry_run else ".video-report.csv"
    return Path(f"{output_dir}{suffix}")


def state_dir(output_dir: Path) -> Path:
    return Path(f"{output_dir}.video-state")
