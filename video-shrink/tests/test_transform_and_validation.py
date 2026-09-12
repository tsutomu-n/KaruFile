from __future__ import annotations

import json
import re
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from video_shrink.config import CompactRecipe, VideoConfig
from video_shrink.ffmpeg import CommandResult, ToolError
from video_shrink.models import Eligibility, MediaInfo, Preset, QualityResult, StreamInfo, ToolInfo
from video_shrink import transform, validate


def _tools() -> ToolInfo:
    return ToolInfo(Path("ffmpeg"), Path("ffprobe"), "ffmpeg test", "ffprobe test")


def _eligibility(audio: StreamInfo | None = None) -> Eligibility:
    video = StreamInfo(index=0, codec_type="video", codec_name="h264")
    return Eligibility(
        True,
        None,
        "eligible",
        video=video,
        audio=audio,
        target_width=1280,
        target_height=720,
        target_fps=Fraction(30, 1),
        duration=2.0,
    )


@pytest.mark.parametrize(
    ("suffix", "muxer", "encoder"),
    [(".mp4", "mp4", "aac"), (".m4v", "mp4", "aac"), (".mkv", "matroska", "libopus"), (".webm", "webm", "libopus")],
)
def test_encode_command_has_fixed_safe_container_and_codecs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str, muxer: str, encoder: str
) -> None:
    source = tmp_path / f"source{suffix}"
    destination = tmp_path / f"candidate.tmp{suffix}"
    source.write_bytes(b"source")
    audio = StreamInfo(index=1, codec_type="audio", codec_name="aac", channels=2, sample_rate=44_100)
    captured: list[str] = []

    def fake_run(argv, **kwargs):
        captured.extend(str(value) for value in argv)
        destination.write_bytes(b"candidate")
        return CommandResult(tuple(captured), 0, "", "")

    monkeypatch.setattr(transform, "run_command", fake_run)
    config = VideoConfig(tmp_path / "in", tmp_path / "out", preset=Preset.COMPACT)
    transform.encode_candidate(_tools(), source, destination, _eligibility(audio), config, crf=38)
    command = " ".join(captured)
    assert "-protocol_whitelist file,pipe" in command
    assert "-c:v libsvtav1" in command
    assert f"-c:a {encoder}" in command
    assert f"-f {muxer}" in command
    assert "-map_chapters -1" in command
    assert "-sn -dn" in command
    assert "-fps_mode cfr" in command


def test_encode_without_audio_explicitly_disables_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    destination = tmp_path / "candidate.tmp.mp4"
    source.write_bytes(b"source")
    captured: list[str] = []

    def fake_run(argv, **kwargs):
        captured.extend(str(value) for value in argv)
        destination.write_bytes(b"candidate")
        return CommandResult(tuple(captured), 0, "", "")

    monkeypatch.setattr(transform, "run_command", fake_run)
    transform.encode_candidate(
        _tools(),
        source,
        destination,
        _eligibility(),
        VideoConfig(tmp_path / "in", tmp_path / "out", preset=Preset.COMPACT),
        crf=38,
    )
    assert "-an" in captured


def test_vmaf_parser_calculates_mean_and_lower_five_percentile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "candidate.mp4"
    source = tmp_path / "source.mp4"
    candidate.write_bytes(b"candidate")
    source.write_bytes(b"source")

    def fake_run(argv, **kwargs):
        graph = str(argv[argv.index("-lavfi") + 1])
        name = re.search(r"log_path=([^:]+):", graph).group(1)
        frames = [{"metrics": {"vmaf": value}} for value in range(1, 101)]
        (kwargs["cwd"] / name).write_text(json.dumps({"frames": frames}), encoding="utf-8")
        return CommandResult(tuple(str(value) for value in argv), 0, "", "")

    monkeypatch.setattr(validate, "run_command", fake_run)
    quality = validate.measure_vmaf(
        _tools(),
        candidate,
        source,
        _eligibility(),
        2.0,
        tmp_path,
        VideoConfig(tmp_path / "in", tmp_path / "out", preset=Preset.COMPACT),
    )
    assert quality == QualityResult(mean=50.5, p5=5.0, frame_count=100)
    assert not list(tmp_path.glob("vmaf-*.json"))


def test_vmaf_rejects_missing_scores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = tmp_path / "candidate.mp4"
    source = tmp_path / "source.mp4"
    candidate.write_bytes(b"candidate")
    source.write_bytes(b"source")

    def fake_run(argv, **kwargs):
        graph = str(argv[argv.index("-lavfi") + 1])
        name = re.search(r"log_path=([^:]+):", graph).group(1)
        (kwargs["cwd"] / name).write_text('{"frames": []}', encoding="utf-8")
        return CommandResult(tuple(str(value) for value in argv), 0, "", "")

    monkeypatch.setattr(validate, "run_command", fake_run)
    with pytest.raises(ToolError, match="no frame scores"):
        validate.measure_vmaf(
            _tools(), candidate, source, _eligibility(), 2.0, tmp_path,
            VideoConfig(tmp_path / "in", tmp_path / "out", preset=Preset.COMPACT),
        )


def test_compact_recipe_rejects_invalid_threshold_configuration() -> None:
    with pytest.raises(ValueError):
        CompactRecipe(crf_ladder=())
    with pytest.raises(ValueError):
        CompactRecipe(vmaf_subsample=0)
    with pytest.raises(ValueError):
        CompactRecipe(crf_ladder=(32, 38))
    with pytest.raises(ValueError):
        CompactRecipe(min_saved_percent=1.1)
    with pytest.raises(ValueError):
        CompactRecipe(vmaf_model="model:injected=1")
    with pytest.raises(ValueError):
        CompactRecipe(vmaf_min_mean=60, vmaf_min_p5=70)


def _structure_fixture(tmp_path: Path) -> tuple[MediaInfo, MediaInfo, Eligibility, VideoConfig]:
    source_video = StreamInfo(
        index=0,
        codec_type="video",
        codec_name="h264",
        width=1920,
        height=1080,
        pix_fmt="yuv420p",
        field_order="progressive",
        sample_aspect_ratio="1:1",
        r_frame_rate=Fraction(60, 1),
        avg_frame_rate=Fraction(60, 1),
        duration=10.0,
    )
    source_audio = StreamInfo(
        index=1,
        codec_type="audio",
        codec_name="aac",
        channels=2,
        sample_rate=96_000,
        duration=10.0,
    )
    candidate_video = StreamInfo(
        index=0,
        codec_type="video",
        codec_name="av1",
        width=1280,
        height=720,
        pix_fmt="yuv420p",
        field_order="progressive",
        sample_aspect_ratio="1:1",
        r_frame_rate=Fraction(30, 1),
        avg_frame_rate=Fraction(30, 1),
        duration=10.0,
    )
    candidate_audio = StreamInfo(
        index=1,
        codec_type="audio",
        codec_name="aac",
        channels=2,
        sample_rate=48_000,
        duration=10.0,
    )
    source = MediaInfo(
        tmp_path / "source.mp4", "mov,mp4", 10.0, (source_video, source_audio)
    )
    candidate = MediaInfo(
        tmp_path / "candidate.mp4", "mov,mp4", 10.0, (candidate_video, candidate_audio)
    )
    eligibility = Eligibility(
        True,
        None,
        "eligible",
        video=source_video,
        audio=source_audio,
        target_width=1280,
        target_height=720,
        target_fps=Fraction(30, 1),
        duration=10.0,
    )
    config = VideoConfig(tmp_path / "in", tmp_path / "out", preset=Preset.COMPACT)
    return source, candidate, eligibility, config


def test_candidate_structure_requires_explicit_geometry_audio_plan_and_durations(
    tmp_path: Path,
) -> None:
    source, candidate, eligibility, config = _structure_fixture(tmp_path)
    validate.validate_structure(candidate, source, eligibility, config)


def test_av1_missing_field_order_and_muted_duration_follow_video_plan(tmp_path: Path) -> None:
    source, candidate, eligibility, config = _structure_fixture(tmp_path)
    # A longer audio tail must not prevent a valid silent video from being published.
    source = replace(source, duration=20.0)
    video = replace(candidate.video_streams[0], field_order="")
    silent = replace(candidate, streams=(video,))
    plan = replace(eligibility, audio=None)
    mute = replace(config, remove_audio=True)
    validate.validate_structure(silent, source, plan, mute)
    with pytest.raises(ToolError, match="audio stream count"):
        validate.validate_structure(candidate, source, plan, mute)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"field_order": "tt"}, "progressive"),
        ({"sample_aspect_ratio": "N/A"}, "sample aspect ratio"),
        ({"tags": {"rotate": "90"}}, "rotation"),
        ({"duration": 8.0}, "video stream duration"),
    ],
)
def test_candidate_video_contract_rejects_unknown_or_changed_values(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    source, candidate, eligibility, config = _structure_fixture(tmp_path)
    changed = replace(candidate.video_streams[0], **change)
    candidate = replace(candidate, streams=(changed, candidate.audio_streams[0]))
    with pytest.raises(ToolError, match=message):
        validate.validate_structure(candidate, source, eligibility, config)


def test_candidate_audio_sample_rate_and_stream_duration_must_match_plan(
    tmp_path: Path,
) -> None:
    source, candidate, eligibility, config = _structure_fixture(tmp_path)
    wrong_rate = replace(candidate.audio_streams[0], sample_rate=44_100)
    with pytest.raises(ToolError, match="sample rate"):
        validate.validate_structure(
            replace(candidate, streams=(candidate.video_streams[0], wrong_rate)),
            source,
            eligibility,
            config,
        )
    short_audio = replace(candidate.audio_streams[0], duration=7.0)
    with pytest.raises(ToolError, match="audio stream duration"):
        validate.validate_structure(
            replace(candidate, streams=(candidate.video_streams[0], short_audio)),
            source,
            eligibility,
            config,
        )


def test_stream_duration_is_compared_only_when_both_sides_report_it(tmp_path: Path) -> None:
    source, candidate, eligibility, config = _structure_fixture(tmp_path)
    source_video = replace(source.video_streams[0], duration=None)
    source = replace(source, streams=(source_video, source.audio_streams[0]))
    eligibility = replace(eligibility, video=source_video)
    candidate_video = replace(candidate.video_streams[0], duration=1.0)
    candidate = replace(candidate, streams=(candidate_video, candidate.audio_streams[0]))
    validate.validate_structure(candidate, source, eligibility, config)
