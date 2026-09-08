from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

import pytest

from video_shrink.config import CompactRecipe, VideoConfig, report_path, state_dir
from video_shrink.ffmpeg import ToolError
from video_shrink.models import Preset, ProcessStatus, QualityResult, ToolInfo
from video_shrink import runner


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    return source, output


def _read_report(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_standard_atomically_copies_and_reuses_verified_output(tmp_path: Path) -> None:
    source, output = _paths(tmp_path)
    clip = source / "nested" / "clip.mp4"
    clip.parent.mkdir()
    clip.write_bytes(b"original-video")
    config = VideoConfig(source, output, preset=Preset.STANDARD)

    first = runner.run(config)
    assert first.exit_code == 0
    assert first.results[0].status is ProcessStatus.SKIPPED_STANDARD
    assert (output / "nested" / "clip.mp4").read_bytes() == b"original-video"
    assert first.report_path == report_path(output, dry_run=False)
    assert (state_dir(output) / "state.sqlite3").is_file()

    second = runner.run(config)
    assert second.exit_code == 0
    assert second.results[0].status is ProcessStatus.SKIPPED_COMPLETE


def test_same_size_output_tamper_is_not_reused(tmp_path: Path) -> None:
    source, output = _paths(tmp_path)
    clip = source / "clip.mp4"
    clip.write_bytes(b"good")
    config = VideoConfig(source, output, preset=Preset.STANDARD)
    assert runner.run(config).exit_code == 0
    (output / "clip.mp4").write_bytes(b"evil")
    outcome = runner.run(config)
    assert outcome.results[0].status is ProcessStatus.SKIPPED_STANDARD
    assert (output / "clip.mp4").read_bytes() == b"good"


def test_standard_dry_run_creates_only_state_and_dry_report(tmp_path: Path) -> None:
    source, output = _paths(tmp_path)
    (source / "clip.mp4").write_bytes(b"video")
    outcome = runner.run(VideoConfig(source, output, preset=Preset.STANDARD, dry_run=True))
    assert outcome.exit_code == 0
    assert outcome.results[0].status is ProcessStatus.DRY_RUN
    assert not output.exists()
    assert report_path(output, dry_run=True).is_file()
    assert not report_path(output, dry_run=False).exists()
    assert (state_dir(output) / "state.sqlite3").is_file()


def test_report_has_required_columns_and_current_input_rows(tmp_path: Path) -> None:
    source, output = _paths(tmp_path)
    (source / "b.webm").write_bytes(b"b")
    (source / "a.mp4").write_bytes(b"a")
    outcome = runner.run(VideoConfig(source, output, preset=Preset.STANDARD, workers=2))
    rows = _read_report(outcome.report_path)
    required = {
        "source_path", "source_size", "output_size", "saved_bytes", "status",
        "error_message", "preset",
    }
    assert required <= rows[0].keys()
    assert [Path(row["source_path"]).name for row in rows] == ["a.mp4", "b.webm"]

    (source / "a.mp4").unlink()
    rerun = runner.run(VideoConfig(source, output, preset=Preset.STANDARD))
    assert [Path(row["source_path"]).name for row in _read_report(rerun.report_path)] == ["b.webm"]


def test_compact_adopts_only_after_quality_and_savings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, media_factory
) -> None:
    source, output = _paths(tmp_path)
    clip = source / "clip.mp4"
    clip.write_bytes(b"S" * 1000)
    source_info = media_factory(clip)
    tools = ToolInfo(Path("ffmpeg"), Path("ffprobe"), "ffmpeg test", "ffprobe test")
    monkeypatch.setattr(runner, "prepare_tools", lambda *args: tools)
    monkeypatch.setattr(runner, "probe_media", lambda *args: source_info)

    def fake_encode(_tools, _source, destination, _eligibility, _config, *, crf):
        assert crf == 38
        destination.write_bytes(b"C" * 400)

    monkeypatch.setattr(runner, "encode_candidate", fake_encode)
    monkeypatch.setattr(
        runner,
        "validate_candidate",
        lambda *args: (replace(source_info, path=args[1]), QualityResult(95.0, 90.0, 60)),
    )
    recipe = CompactRecipe(crf_ladder=(38,), min_saved_bytes=1, min_saved_percent=0.10)
    outcome = runner.run(VideoConfig(source, output, preset=Preset.COMPACT, recipe=recipe))
    assert outcome.exit_code == 0
    result = outcome.results[0]
    assert result.status is ProcessStatus.ADOPTED
    assert result.output_size == 400
    assert result.saved_bytes == 600
    assert result.vmaf_mean == 95.0
    assert (output / "clip.mp4").read_bytes() == b"C" * 400


def test_quality_rejection_publishes_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, media_factory
) -> None:
    source, output = _paths(tmp_path)
    clip = source / "clip.mp4"
    clip.write_bytes(b"S" * 1000)
    source_info = media_factory(clip)
    tools = ToolInfo(Path("ffmpeg"), Path("ffprobe"), "ffmpeg test", "ffprobe test")
    monkeypatch.setattr(runner, "prepare_tools", lambda *args: tools)
    monkeypatch.setattr(runner, "probe_media", lambda *args: source_info)
    monkeypatch.setattr(
        runner,
        "encode_candidate",
        lambda _tools, _source, destination, *_args, **_kwargs: destination.write_bytes(b"C" * 300),
    )
    monkeypatch.setattr(
        runner,
        "validate_candidate",
        lambda *args: (replace(source_info, path=args[1]), QualityResult(40.0, 20.0, 60)),
    )
    recipe = CompactRecipe(crf_ladder=(38,), min_saved_bytes=1)
    outcome = runner.run(VideoConfig(source, output, preset=Preset.COMPACT, recipe=recipe))
    assert outcome.results[0].status is ProcessStatus.UNCHANGED
    assert (output / "clip.mp4").read_bytes() == clip.read_bytes()


def test_encode_failure_reports_error_and_preserves_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, media_factory
) -> None:
    source, output = _paths(tmp_path)
    clip = source / "clip.mp4"
    clip.write_bytes(b"source")
    output.mkdir()
    destination = output / "clip.mp4"
    destination.write_bytes(b"healthy-existing")
    tools = ToolInfo(Path("ffmpeg"), Path("ffprobe"), "ffmpeg test", "ffprobe test")
    monkeypatch.setattr(runner, "prepare_tools", lambda *args: tools)
    monkeypatch.setattr(runner, "probe_media", lambda *args: media_factory(clip))
    monkeypatch.setattr(
        runner, "encode_candidate", lambda *args, **kwargs: (_ for _ in ()).throw(ToolError("boom"))
    )
    outcome = runner.run(VideoConfig(source, output, preset=Preset.COMPACT))
    assert outcome.exit_code == 1
    assert outcome.results[0].status is ProcessStatus.ERROR
    assert destination.read_bytes() == b"healthy-existing"
    assert not list(output.glob(".*.tmp.mp4"))


def test_missing_tools_is_error_but_recovers_original_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = _paths(tmp_path)
    (source / "a.mp4").write_bytes(b"a")
    (source / "b.mkv").write_bytes(b"b")
    monkeypatch.setattr(
        runner, "prepare_tools", lambda *args: (_ for _ in ()).throw(ToolError("missing libvmaf"))
    )
    outcome = runner.run(VideoConfig(source, output, preset=Preset.COMPACT))
    assert outcome.exit_code == 1
    assert [result.status for result in outcome.results] == [ProcessStatus.ERROR, ProcessStatus.ERROR]
    assert (output / "a.mp4").read_bytes() == b"a"
    assert (output / "b.mkv").read_bytes() == b"b"
    assert all("original copied as recovery" in result.error_message for result in outcome.results)


def test_cli_workers_must_be_positive() -> None:
    from video_shrink.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["run", "--input", "in", "--output", "out", "--workers", "0"]
        )


def test_input_and_output_must_not_overlap(tmp_path: Path) -> None:
    source = tmp_path / "input"
    source.mkdir()
    (source / "clip.mp4").write_bytes(b"video")
    same = runner.run(VideoConfig(source, source, preset=Preset.STANDARD))
    nested = runner.run(VideoConfig(source, source / "output", preset=Preset.STANDARD))
    assert same.exit_code == 1 and same.report_path is None
    assert nested.exit_code == 1 and nested.report_path is None


def test_existing_destination_hardlink_is_rejected_without_modification(tmp_path: Path) -> None:
    source, output = _paths(tmp_path)
    clip = source / "clip.mp4"
    clip.write_bytes(b"original")
    output.mkdir()
    destination = output / "clip.mp4"
    try:
        destination.hardlink_to(clip)
    except OSError:
        pytest.skip("hardlinks are unavailable on this filesystem")
    outcome = runner.run(VideoConfig(source, output, preset=Preset.STANDARD))
    assert outcome.exit_code == 1
    assert outcome.report_path is None
    assert clip.read_bytes() == b"original"
    assert destination.read_bytes() == b"original"


@pytest.mark.parametrize("operation", ["get", "reuse", "save", "close"])
def test_state_operation_failure_returns_nonzero_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    source, output = _paths(tmp_path)
    (source / "clip.mp4").write_bytes(b"video")
    if operation == "get":
        monkeypatch.setattr(
            runner.state,
            "get_record",
            lambda *args: (_ for _ in ()).throw(RuntimeError("state get failed")),
        )
    elif operation == "reuse":
        monkeypatch.setattr(
            runner.state,
            "reusable_result",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("state reuse failed")),
        )
    elif operation == "save":
        monkeypatch.setattr(
            runner.state,
            "save_result",
            lambda *args: (_ for _ in ()).throw(RuntimeError("state save failed")),
        )
    else:
        class BadCloseConnection:
            def close(self):
                raise RuntimeError("state close failed")

        monkeypatch.setattr(runner.state, "init_db", lambda *args: BadCloseConnection())
        monkeypatch.setattr(runner.state, "get_record", lambda *args: None)
        monkeypatch.setattr(runner.state, "save_result", lambda *args: None)
    outcome = runner.run(VideoConfig(source, output, preset=Preset.STANDARD))
    assert outcome.exit_code == 1
    assert outcome.report_path is None


def test_dry_run_neither_reads_nor_overwrites_success_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = _paths(tmp_path)
    (source / "clip.mp4").write_bytes(b"video")
    actual = runner.run(VideoConfig(source, output, preset=Preset.STANDARD))
    assert actual.exit_code == 0

    monkeypatch.setattr(
        runner.state,
        "get_record",
        lambda *args: (_ for _ in ()).throw(AssertionError("dry-run read state")),
    )
    monkeypatch.setattr(
        runner.state,
        "save_result",
        lambda *args: (_ for _ in ()).throw(AssertionError("dry-run saved state")),
    )
    dry = runner.run(VideoConfig(source, output, preset=Preset.STANDARD, dry_run=True))
    assert dry.exit_code == 0
    assert dry.results[0].status is ProcessStatus.DRY_RUN

    monkeypatch.undo()
    reused = runner.run(VideoConfig(source, output, preset=Preset.STANDARD))
    assert reused.results[0].status is ProcessStatus.SKIPPED_COMPLETE


@pytest.mark.parametrize(
    "video_change",
    [{"field_order": ""}, {"sample_aspect_ratio": "N/A"}],
)
def test_unknown_progressive_or_sar_is_copied_as_complex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    media_factory,
    video_change: dict[str, object],
) -> None:
    source, output = _paths(tmp_path)
    clip = source / "clip.mp4"
    clip.write_bytes(b"original")
    media = media_factory(clip)
    changed_video = replace(media.video_streams[0], **video_change)
    source_info = replace(media, streams=(changed_video,))
    tools = ToolInfo(Path("ffmpeg"), Path("ffprobe"), "ffmpeg test", "ffprobe test")
    monkeypatch.setattr(runner, "prepare_tools", lambda *args: tools)
    monkeypatch.setattr(runner, "probe_media", lambda *args: source_info)
    outcome = runner.run(VideoConfig(source, output, preset=Preset.COMPACT))
    assert outcome.exit_code == 0
    assert outcome.results[0].status is ProcessStatus.SKIPPED_COMPLEX
    assert (output / "clip.mp4").read_bytes() == b"original"
