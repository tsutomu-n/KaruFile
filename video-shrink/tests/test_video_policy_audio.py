from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from video_shrink import runner, transform, validate
from video_shrink.config import CompactRecipe, VideoConfig
from video_shrink.ffmpeg import CommandResult, ToolError
from video_shrink.models import Preset, ProcessStatus, QualityResult, ToolInfo
from video_shrink.probe import inspect_eligibility


def test_default_accepts_phone_metadata_but_safe_rejects(tmp_path, media_factory):
    media = media_factory(tmp_path / "phone.mp4")
    video = replace(media.video_streams[0], field_order="", sample_aspect_ratio="",
                    r_frame_rate=Fraction(30), avg_frame_rate=Fraction(128750, 4293))
    media = replace(media, streams=(video,))
    plan = inspect_eligibility(media, CompactRecipe())
    assert plan.eligible and plan.target_fps == 30
    assert not inspect_eligibility(media, CompactRecipe(), safe=True).eligible
    assert not inspect_eligibility(replace(media, streams=(replace(video, field_order="tt"),)), CompactRecipe()).eligible


def test_remove_audio_maps_no_audio_and_rejects_audible_candidate(tmp_path, media_factory, stereo_audio, monkeypatch):
    media = media_factory(tmp_path / "phone.mp4", audio=stereo_audio,
                          extras=(replace(stereo_audio, index=2, channels=6),))
    plan = inspect_eligibility(media, CompactRecipe(), remove_audio=True)
    assert plan.eligible and plan.audio is None
    assert not inspect_eligibility(media, CompactRecipe()).eligible
    config = VideoConfig(tmp_path / "in", tmp_path / "out", preset=Preset.COMPACT, remove_audio=True)
    destination = tmp_path / "candidate.mp4"
    captured = []
    def command(argv, **kwargs):
        captured.extend(map(str, argv))
        destination.write_bytes(b"candidate")
        return CommandResult(tuple(captured), 0, "", "")
    monkeypatch.setattr(transform, "run_command", command)
    tools = ToolInfo(Path("ffmpeg"), Path("ffprobe"), "test", "test")
    transform.encode_candidate(tools, media.path, destination, plan, config, crf=38)
    assert "-an" in captured and captured.count("-map") == 1 and "-c:a" not in captured
    with pytest.raises(ToolError, match="audio stream count"):
        validate.validate_structure(media, media, plan, config)


@pytest.mark.parametrize("failure", ["quality", "savings", "tool", "unsupported"])
def test_mute_failure_never_copies_audible_source(tmp_path, media_factory, stereo_audio, monkeypatch, failure):
    source = tmp_path / "input"
    source.mkdir()
    clip = source / "clip.mp4"
    clip.write_bytes(b"source" * 1000)
    output = tmp_path / "output"
    media = media_factory(clip, audio=stereo_audio, chapters=int(failure == "unsupported"))
    tools = ToolInfo(Path("ffmpeg"), Path("ffprobe"), "test", "test")
    monkeypatch.setattr(runner, "prepare_tools", lambda *a: tools)
    monkeypatch.setattr(runner, "probe_media", lambda *a: media)
    def encode(_tools, _source, destination, *args, **kwargs):
        if failure == "tool":
            raise ToolError("encode failed")
        destination.write_bytes(b"candidate")
    monkeypatch.setattr(runner, "encode_candidate", encode)
    monkeypatch.setattr(runner, "validate_candidate", lambda *a: (media, QualityResult(20 if failure == "quality" else 95, 90, 10)))
    recipe = CompactRecipe(crf_ladder=(38,), min_saved_bytes=10000 if failure == "savings" else 1)
    outcome = runner.run(VideoConfig(source, output, preset=Preset.COMPACT, remove_audio=True, recipe=recipe))
    assert outcome.exit_code == 1 and outcome.results[0].status is ProcessStatus.ERROR
    assert not (output / clip.name).exists()
    assert clip.read_bytes() == b"source" * 1000


def test_policy_hash_and_reuse_do_not_restore_audio(tmp_path, media_factory, stereo_audio, monkeypatch):
    source = tmp_path / "input"
    source.mkdir()
    clip = source / "clip.mp4"
    clip.write_bytes(b"source" * 1000)
    config = VideoConfig(source, tmp_path / "output", preset=Preset.COMPACT, recipe=CompactRecipe(min_saved_bytes=1))
    tools = ToolInfo(Path("ffmpeg"), Path("ffprobe"), "test", "test")
    assert len({config.processing_hash(tools), replace(config, safe=True).processing_hash(tools),
                replace(config, remove_audio=True).processing_hash(tools)}) == 3
    media = media_factory(clip, audio=stereo_audio)
    monkeypatch.setattr(runner, "prepare_tools", lambda *a: tools)
    monkeypatch.setattr(runner, "probe_media", lambda *a: media)
    calls = []
    def encode(_tools, _source, destination, plan, *args, **kwargs):
        calls.append(plan.audio)
        destination.write_bytes(b"silent" if plan.audio is None else b"audible")
    monkeypatch.setattr(runner, "encode_candidate", encode)
    monkeypatch.setattr(runner, "validate_candidate", lambda *a: (media, QualityResult(95, 90, 10)))
    assert runner.run(config).results[0].audio_codec == "aac"
    mute = replace(config, remove_audio=True)
    assert runner.run(mute).results[0].status is ProcessStatus.ADOPTED
    reused = runner.run(mute).results[0]
    assert reused.status is ProcessStatus.SKIPPED_COMPLETE
    assert reused.remove_audio and not reused.audio_codec and len(calls) == 2
    assert reused.as_csv_row()["remove_audio"] == "true"


def test_standard_rejects_video_options(tmp_path):
    from video_shrink.cli import main
    with pytest.raises(ValueError, match="compact"):
        VideoConfig(tmp_path, tmp_path / "out", remove_audio=True)
    with pytest.raises(SystemExit) as error:
        main(["run", "--input", str(tmp_path), "--output", str(tmp_path / "out"), "--safe"])
    assert error.value.code == 2
