"""ffprobe JSON parsing and conservative compact eligibility."""
from __future__ import annotations

import json
import math
from fractions import Fraction
from pathlib import Path
from typing import Any

from .config import CompactRecipe
from .ffmpeg import ToolError, command_detail, run_command
from .models import Eligibility, MediaInfo, ProcessStatus, StreamInfo, ToolInfo


_SDR_420_FORMATS = frozenset({"yuv420p", "yuvj420p"})
_HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67"})
_HDR_PRIMARIES = frozenset({"bt2020"})
_EXPECTED_FORMATS = {
    ".mp4": ("mov", "mp4"),
    ".m4v": ("mov", "mp4"),
    ".mkv": ("matroska",),
    ".webm": ("webm", "matroska"),
}


def _optional_int(value: Any) -> int | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def parse_fraction(value: Any) -> Fraction | None:
    if value in (None, "", "N/A", "0/0"):
        return None
    try:
        parsed = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None
    return parsed if parsed > 0 else None


def _string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        try:
            result[str(key)] = int(item)
        except (TypeError, ValueError):
            continue
    return result


def parse_probe_json(path: Path, payload: str) -> MediaInfo:
    try:
        root = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ToolError(f"ffprobe returned invalid JSON: {exc}") from exc
    if not isinstance(root, dict):
        raise ToolError("ffprobe JSON root is not an object")
    raw_streams = root.get("streams")
    raw_format = root.get("format")
    raw_chapters = root.get("chapters", [])
    if not isinstance(raw_streams, list) or not isinstance(raw_format, dict):
        raise ToolError("ffprobe JSON is missing streams or format")
    streams: list[StreamInfo] = []
    for raw in raw_streams:
        if not isinstance(raw, dict):
            raise ToolError("ffprobe stream entry is not an object")
        side_data = raw.get("side_data_list", [])
        streams.append(
            StreamInfo(
                index=int(raw.get("index", len(streams))),
                codec_type=str(raw.get("codec_type", "")),
                codec_name=str(raw.get("codec_name", "")),
                profile=str(raw.get("profile", "")),
                width=_optional_int(raw.get("width")),
                height=_optional_int(raw.get("height")),
                pix_fmt=str(raw.get("pix_fmt", "")),
                field_order=str(raw.get("field_order", "")),
                sample_aspect_ratio=str(raw.get("sample_aspect_ratio", "")),
                r_frame_rate=parse_fraction(raw.get("r_frame_rate")),
                avg_frame_rate=parse_fraction(raw.get("avg_frame_rate")),
                color_primaries=str(raw.get("color_primaries", "")),
                color_transfer=str(raw.get("color_transfer", "")),
                color_space=str(raw.get("color_space", "")),
                bits_per_raw_sample=_optional_int(raw.get("bits_per_raw_sample")),
                channels=_optional_int(raw.get("channels")),
                sample_rate=_optional_int(raw.get("sample_rate")),
                bit_rate=_optional_int(raw.get("bit_rate")),
                duration=_optional_float(raw.get("duration")),
                disposition=_int_mapping(raw.get("disposition")),
                tags=_string_mapping(raw.get("tags")),
                side_data=tuple(item for item in side_data if isinstance(item, dict))
                if isinstance(side_data, list)
                else (),
            )
        )
    duration = _optional_float(raw_format.get("duration"))
    if duration is None or duration <= 0:
        raise ToolError("video duration is missing or not positive")
    return MediaInfo(
        path=path,
        format_name=str(raw_format.get("format_name", "")),
        duration=duration,
        streams=tuple(streams),
        chapter_count=len(raw_chapters) if isinstance(raw_chapters, list) else 0,
    )


def probe_media(tools: ToolInfo, path: Path, recipe: CompactRecipe) -> MediaInfo:
    result = run_command(
        [
            tools.ffprobe,
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-show_streams",
            "-show_format",
            "-show_chapters",
            "-of",
            "json",
            "-i",
            path,
        ],
        timeout=recipe.probe_timeout_seconds,
        max_output_bytes=recipe.max_subprocess_output_bytes,
        require_complete_stdout=True,
    )
    if result.timed_out or result.returncode != 0:
        raise ToolError(f"ffprobe failed for {path}: {command_detail(result)}")
    return parse_probe_json(path, result.stdout)


def display_rotation(stream: StreamInfo) -> int | None:
    values: list[float] = []
    for key, value in stream.tags.items():
        if key.casefold() == "rotate":
            try:
                values.append(float(value))
            except ValueError:
                return None
    for item in stream.side_data:
        if "rotation" in item:
            try:
                values.append(float(item["rotation"]))
            except (TypeError, ValueError):
                return None
    if not values:
        return 0
    normalized = {int(round(value)) % 360 for value in values if abs(value - round(value)) < 0.01}
    if len(normalized) != 1:
        return None
    value = normalized.pop()
    return value if value in {0, 90, 180, 270} else None


def _has_hdr_metadata(stream: StreamInfo) -> bool:
    if stream.color_transfer.casefold() in _HDR_TRANSFERS:
        return True
    if stream.color_primaries.casefold() in _HDR_PRIMARIES:
        return True
    serialized = json.dumps(stream.side_data, ensure_ascii=False).casefold()
    return any(
        marker in serialized
        for marker in (
            "dovi",
            "dolby vision",
            "mastering display metadata",
            "content light level metadata",
        )
    )


def target_dimensions(width: int, height: int, recipe: CompactRecipe) -> tuple[int, int]:
    scale = min(1.0, recipe.max_width / width, recipe.max_height / height)
    target_width = max(2, int(width * scale) // 2 * 2)
    target_height = max(2, int(height * scale) // 2 * 2)
    return target_width, target_height


def inspect_eligibility(media: MediaInfo, recipe: CompactRecipe) -> Eligibility:
    suffix = media.path.suffix.lower()
    expected = _EXPECTED_FORMATS.get(suffix)
    if expected is None or not any(name in media.format_name.casefold() for name in expected):
        return Eligibility(False, ProcessStatus.SKIPPED_UNSUPPORTED, "container does not match suffix")
    if media.chapter_count:
        return Eligibility(False, ProcessStatus.SKIPPED_COMPLEX, "chapters are present")
    unsupported_streams = [
        stream for stream in media.streams if stream.codec_type not in {"video", "audio"}
    ]
    if unsupported_streams:
        kinds = ",".join(sorted({stream.codec_type or "unknown" for stream in unsupported_streams}))
        return Eligibility(False, ProcessStatus.SKIPPED_COMPLEX, f"unsupported streams: {kinds}")
    if len(media.video_streams) != 1:
        return Eligibility(False, ProcessStatus.SKIPPED_COMPLEX, "exactly one video stream is required")
    video = media.video_streams[0]
    if video.disposition.get("attached_pic", 0):
        return Eligibility(False, ProcessStatus.SKIPPED_COMPLEX, "video stream is attached artwork")
    if len(media.audio_streams) > 1:
        return Eligibility(False, ProcessStatus.SKIPPED_COMPLEX, "multiple audio streams are present")
    audio = media.audio_streams[0] if media.audio_streams else None
    if audio is not None and (audio.channels is None or audio.channels not in {1, 2}):
        return Eligibility(False, ProcessStatus.SKIPPED_COMPLEX, "audio must have one or two channels")
    if video.pix_fmt.casefold() not in _SDR_420_FORMATS:
        return Eligibility(False, ProcessStatus.SKIPPED_UNSUPPORTED, "video is not 8-bit YUV 4:2:0")
    if video.bits_per_raw_sample not in (None, 0, 8):
        return Eligibility(False, ProcessStatus.SKIPPED_UNSUPPORTED, "video bit depth is not 8-bit")
    if _has_hdr_metadata(video):
        return Eligibility(False, ProcessStatus.SKIPPED_COMPLEX, "HDR or Dolby Vision metadata is present")
    if video.field_order.casefold() != "progressive":
        return Eligibility(
            False,
            ProcessStatus.SKIPPED_COMPLEX,
            "progressive field order is not explicitly reported",
        )
    if video.sample_aspect_ratio != "1:1":
        return Eligibility(
            False,
            ProcessStatus.SKIPPED_COMPLEX,
            "1:1 sample aspect ratio is not explicitly reported",
        )
    if video.width is None or video.height is None or video.width < 2 or video.height < 2:
        return Eligibility(False, ProcessStatus.SKIPPED_UNSUPPORTED, "video dimensions are invalid")
    if video.r_frame_rate is None or video.avg_frame_rate is None:
        return Eligibility(False, ProcessStatus.SKIPPED_COMPLEX, "frame rate is unavailable")
    if video.r_frame_rate != video.avg_frame_rate:
        return Eligibility(False, ProcessStatus.SKIPPED_COMPLEX, "variable frame rate is not supported")
    rotation = display_rotation(video)
    if rotation is None:
        return Eligibility(False, ProcessStatus.SKIPPED_COMPLEX, "display transform is unsupported")
    display_width, display_height = video.width, video.height
    if rotation in {90, 270}:
        display_width, display_height = display_height, display_width
    width, height = target_dimensions(display_width, display_height, recipe)
    source_fps = video.avg_frame_rate
    target_fps = min(source_fps, Fraction(recipe.max_fps, 1))
    return Eligibility(
        True,
        None,
        "eligible",
        video=video,
        audio=audio,
        rotation=rotation,
        display_width=display_width,
        display_height=display_height,
        target_width=width,
        target_height=height,
        source_fps=source_fps,
        target_fps=target_fps,
        duration=media.duration,
    )
