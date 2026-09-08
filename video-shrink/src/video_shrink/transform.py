"""FFmpeg candidate generation."""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from .config import VideoConfig
from .ffmpeg import ToolError, command_detail, run_command
from .models import Eligibility, StreamInfo, ToolInfo


def _rate_text(rate: Fraction) -> str:
    return f"{rate.numerator}/{rate.denominator}"


def output_recipe(path: Path) -> tuple[str, str, str]:
    suffix = path.suffix.lower()
    if suffix in {".mp4", ".m4v"}:
        return "mp4", "aac", "aac"
    if suffix == ".mkv":
        return "matroska", "libopus", "opus"
    if suffix == ".webm":
        return "webm", "libopus", "opus"
    raise ToolError(f"unsupported output container: {suffix}")


def planned_audio_sample_rate(audio: StreamInfo, audio_encoder: str) -> int:
    source_rate = audio.sample_rate if audio.sample_rate and audio.sample_rate > 0 else 48_000
    return 48_000 if audio_encoder == "libopus" else min(source_rate, 48_000)


def encode_candidate(
    tools: ToolInfo,
    source: Path,
    destination: Path,
    eligibility: Eligibility,
    config: VideoConfig,
    *,
    crf: int,
) -> None:
    if not eligibility.eligible or eligibility.video is None or eligibility.target_fps is None:
        raise ValueError("eligible video information is required")
    muxer, audio_encoder, _audio_codec = output_recipe(destination)
    vf = (
        f"scale={eligibility.target_width}:{eligibility.target_height}:flags=lanczos,"
        "setsar=1,"
        f"fps={_rate_text(eligibility.target_fps)},format=yuv420p"
    )
    argv: list[object] = [
        tools.ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-protocol_whitelist",
        "file,pipe",
        "-i",
        source,
        "-map",
        f"0:{eligibility.video.index}",
    ]
    if eligibility.audio is not None:
        argv.extend(["-map", f"0:{eligibility.audio.index}"])
    argv.extend(
        [
            "-map_chapters",
            "-1",
            "-map_metadata",
            "0",
            "-sn",
            "-dn",
            "-vf",
            vf,
            "-fps_mode",
            "cfr",
            "-c:v",
            "libsvtav1",
            "-crf",
            str(crf),
            "-preset",
            str(config.recipe.encoder_preset),
            "-svtav1-params",
            "tune=0",
            "-metadata:s:v:0",
            "rotate=0",
        ]
    )
    if muxer == "mp4":
        argv.extend(["-tag:v", "av01", "-movflags", "+faststart"])
    if eligibility.audio is None:
        argv.append("-an")
    else:
        channels = eligibility.audio.channels or 2
        bit_rate = (
            config.recipe.audio_bitrate_mono
            if channels == 1
            else config.recipe.audio_bitrate_stereo
        )
        sample_rate = planned_audio_sample_rate(eligibility.audio, audio_encoder)
        argv.extend(
            [
                "-c:a",
                audio_encoder,
                "-b:a",
                str(bit_rate),
                "-ac",
                str(channels),
                "-ar",
                str(sample_rate),
            ]
        )
    argv.extend(["-f", muxer, "-y", destination])
    result = run_command(
        argv,
        timeout=config.recipe.encode_timeout(eligibility.duration),
        max_output_bytes=config.recipe.max_subprocess_output_bytes,
    )
    if result.timed_out or result.returncode != 0:
        raise ToolError(f"FFmpeg encode failed: {command_detail(result)}")
    if not destination.is_file() or destination.stat().st_size <= 0:
        raise ToolError("FFmpeg did not create a non-empty candidate")
