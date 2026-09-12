"""Structural, decode, and perceptual validation."""
from __future__ import annotations

import json
import math
import os
import uuid
from pathlib import Path

from .config import VideoConfig
from .ffmpeg import ToolError, command_detail, run_command
from .models import Eligibility, MediaInfo, QualityResult, ToolInfo
from .probe import display_rotation, probe_media
from .transform import output_recipe, planned_audio_sample_rate


def _close_enough(actual: float, expected: float, tolerance: float) -> bool:
    return abs(actual - expected) <= tolerance


def validate_structure(
    candidate: MediaInfo,
    source: MediaInfo,
    eligibility: Eligibility,
    config: VideoConfig,
) -> None:
    if eligibility.video is None:
        raise ToolError("source video plan is missing")
    if len(candidate.video_streams) != 1:
        raise ToolError("candidate does not contain exactly one video stream")
    if len(candidate.audio_streams) != (1 if eligibility.audio is not None else 0):
        raise ToolError("candidate audio stream count changed")
    if candidate.chapter_count:
        raise ToolError("candidate unexpectedly contains chapters")
    if any(stream.codec_type not in {"video", "audio"} for stream in candidate.streams):
        raise ToolError("candidate contains an unexpected stream type")
    video = candidate.video_streams[0]
    if video.codec_name.casefold() != "av1":
        raise ToolError(f"candidate video codec is {video.codec_name}, expected AV1")
    if video.width != eligibility.target_width or video.height != eligibility.target_height:
        raise ToolError(
            f"candidate dimensions are {video.width}x{video.height}, expected "
            f"{eligibility.target_width}x{eligibility.target_height}"
        )
    if video.pix_fmt.casefold() != "yuv420p":
        raise ToolError(f"candidate pixel format is {video.pix_fmt}, expected yuv420p")
    if video.sample_aspect_ratio != "1:1":
        raise ToolError("candidate sample aspect ratio is not 1:1")
    # AV1 is progressive; ffprobe builds may omit this redundant field.
    if video.field_order.casefold() not in {"progressive", "", "unknown"}:
        raise ToolError("candidate is not progressive")
    if display_rotation(video) != 0:
        raise ToolError("candidate display rotation is not zero")
    if eligibility.target_fps is None or video.avg_frame_rate != eligibility.target_fps:
        raise ToolError("candidate frame rate does not match the plan")
    if video.r_frame_rate != video.avg_frame_rate:
        raise ToolError("candidate is not constant frame rate")
    _muxer, audio_encoder, expected_audio = output_recipe(candidate.path)
    if eligibility.audio is not None:
        audio = candidate.audio_streams[0]
        if audio.codec_name.casefold() != expected_audio:
            raise ToolError(
                f"candidate audio codec is {audio.codec_name}, expected {expected_audio}"
            )
        if audio.channels != eligibility.audio.channels:
            raise ToolError("candidate audio channel count changed")
        expected_sample_rate = planned_audio_sample_rate(eligibility.audio, audio_encoder)
        if audio.sample_rate != expected_sample_rate:
            raise ToolError(
                f"candidate audio sample rate is {audio.sample_rate}, "
                f"expected {expected_sample_rate}"
            )

    stream_pairs = [("video", video.duration, eligibility.video.duration)]
    if eligibility.audio is not None:
        stream_pairs.append(
            ("audio", candidate.audio_streams[0].duration, eligibility.audio.duration)
        )
    for label, candidate_duration, source_duration in stream_pairs:
        if (
            candidate_duration is not None
            and source_duration is not None
            and not _close_enough(
                candidate_duration,
                source_duration,
                config.recipe.duration_tolerance_seconds,
            )
        ):
            raise ToolError(
                f"candidate {label} stream duration differs: "
                f"{candidate_duration:.6f} vs {source_duration:.6f}"
            )
    expected_duration = (
        eligibility.video.duration
        if config.remove_audio and eligibility.video.duration else source.duration
    )
    if not _close_enough(
        candidate.duration,
        expected_duration,
        config.recipe.duration_tolerance_seconds,
    ):
        raise ToolError(
            f"candidate duration differs: {candidate.duration:.6f} vs {expected_duration:.6f}"
        )


def full_decode(
    tools: ToolInfo,
    candidate: Path,
    duration: float,
    config: VideoConfig,
) -> None:
    result = run_command(
        [
            tools.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-nostdin",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            candidate,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-f",
            "null",
            "-",
        ],
        timeout=config.recipe.validation_timeout(duration),
        max_output_bytes=config.recipe.max_subprocess_output_bytes,
    )
    if result.timed_out or result.returncode != 0:
        raise ToolError(f"candidate full decode failed: {command_detail(result)}")


def _percentile_5(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.05) - 1)
    return ordered[index]


def measure_vmaf(
    tools: ToolInfo,
    candidate: Path,
    source: Path,
    eligibility: Eligibility,
    duration: float,
    work_dir: Path,
    config: VideoConfig,
) -> QualityResult:
    if eligibility.target_fps is None:
        raise ValueError("target fps is required")
    name = f"vmaf-{uuid.uuid4().hex}.json"
    log_path = work_dir / name
    rate = f"{eligibility.target_fps.numerator}/{eligibility.target_fps.denominator}"
    graph = (
        f"[0:v:0]fps={rate},scale={eligibility.target_width}:{eligibility.target_height}:"
        "flags=bicubic,setpts=PTS-STARTPTS,format=yuv420p[dist];"
        f"[1:v:0]fps={rate},scale={eligibility.target_width}:{eligibility.target_height}:"
        "flags=bicubic,setpts=PTS-STARTPTS,format=yuv420p[ref];"
        f"[dist][ref]libvmaf=log_fmt=json:log_path={name}:"
        f"model=version={config.recipe.vmaf_model}:"
        f"n_subsample={config.recipe.vmaf_subsample}"
    )
    try:
        result = run_command(
            [
                tools.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                candidate,
                "-i",
                source,
                "-lavfi",
                graph,
                "-an",
                "-sn",
                "-f",
                "null",
                "-",
            ],
            timeout=config.recipe.validation_timeout(duration),
            max_output_bytes=config.recipe.max_subprocess_output_bytes,
            cwd=work_dir,
        )
        if result.timed_out or result.returncode != 0:
            raise ToolError(f"VMAF evaluation failed: {command_detail(result)}")
        if not log_path.is_file():
            raise ToolError("VMAF did not produce its JSON log")
        if log_path.stat().st_size > config.recipe.max_vmaf_log_bytes:
            raise ToolError("VMAF JSON log exceeded the configured bound")
        try:
            payload = json.loads(log_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolError(f"VMAF JSON could not be read: {exc}") from exc
        frames = payload.get("frames", []) if isinstance(payload, dict) else []
        values: list[float] = []
        for frame in frames:
            try:
                value = float(frame["metrics"]["vmaf"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(value):
                values.append(value)
        if not values:
            raise ToolError("VMAF JSON contained no frame scores")
        return QualityResult(
            mean=sum(values) / len(values),
            p5=_percentile_5(values),
            frame_count=len(values),
        )
    finally:
        try:
            log_path.unlink(missing_ok=True)
        except OSError:
            pass


def validate_candidate(
    tools: ToolInfo,
    candidate_path: Path,
    source_info: MediaInfo,
    source_path: Path,
    eligibility: Eligibility,
    work_dir: Path,
    config: VideoConfig,
) -> tuple[MediaInfo, QualityResult]:
    candidate_info = probe_media(tools, candidate_path, config.recipe)
    validate_structure(candidate_info, source_info, eligibility, config)
    full_decode(tools, candidate_path, candidate_info.duration, config)
    quality = measure_vmaf(
        tools,
        candidate_path,
        source_path,
        eligibility,
        candidate_info.duration,
        work_dir,
        config,
    )
    return candidate_info, quality
